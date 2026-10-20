"""Contract tests for context_size_nudge.py's tiers, floor and paging, and for
bin/self-slash's /compact-/new gap (2026-10-18 rewrite: the old tests asserted
SOFT_THRESHOLD/HARD_THRESHOLD and a `hermes send` call the hook no longer has)."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2]
REPO = HOOKS_DIR.parents[1]
SELF_SLASH = REPO / "bin" / "self-slash"
sys.path.insert(0, str(HOOKS_DIR))

import context_size_nudge as nudge  # noqa: E402


def _usage(tokens, **extra):
    record = {"message": {"usage": {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": tokens,
    }}}
    record.update(extra)
    return json.dumps(record) + "\n"


def _transcript(tmp_path, *sizes, name="transcript.jsonl"):
    path = tmp_path / name
    path.write_text("".join(_usage(s) for s in sizes))
    return path


def _append(path, text):
    with path.open("a") as f:
        f.write(text)


@pytest.fixture
def hook(monkeypatch, tmp_path, capsys):
    """Run the hook once per call; returns (stdout, pings sent)."""
    monkeypatch.setattr(nudge, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.delenv("HERDR_PANE_ID", raising=False)
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE", raising=False)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    pings = []
    monkeypatch.setattr(
        subprocess, "Popen", lambda cmd, **kwargs: pings.append(cmd),
    )

    def run(session_id, transcript_path):
        payload = json.dumps({
            "session_id": session_id,
            "transcript_path": str(transcript_path),
            "cwd": str(tmp_path),
        })
        monkeypatch.setattr(
            sys, "stdin",
            type("FakeStdin", (), {"read": staticmethod(lambda: payload)})(),
        )
        before = len(pings)
        nudge.main()
        return capsys.readouterr().out, pings[before:]

    run.state = lambda: json.loads((tmp_path / "state.json").read_text())
    return run


def test_constants_match_the_300k_window():
    assert nudge.AUTO_COMPACT_WINDOW == nudge.ASK_TOTAL == 300_000
    assert nudge.PAGE_TOTAL == 400_000
    assert nudge.BOUNDARY_TOTAL == 150_000
    assert nudge.EARLY_GROWTH < nudge.ASK_GROWTH == 200_000


def test_below_early_tier_stays_silent(hook, tmp_path):
    out, pings = hook("s-low", _transcript(tmp_path, 50_000, 50_000 + nudge.EARLY_GROWTH - 1))
    assert out == ""
    assert pings == []


def test_early_message_at_plus_40k(hook, tmp_path):
    out, pings = hook("s-early", _transcript(tmp_path, 50_000, 50_000 + nudge.EARLY_GROWTH))
    assert "Context check" in out
    assert "Do not compact yet" in out
    assert pings == []
    # Same level on the next prompt: no repeat.
    out2, _ = hook("s-early", _transcript(tmp_path, 50_000, 50_000 + nudge.EARLY_GROWTH + 1))
    assert out2 == ""


def test_boundary_note_once_at_150k(hook, tmp_path):
    out, _ = hook("s-bound", _transcript(tmp_path, 120_000, nudge.BOUNDARY_TOTAL - 1))
    assert "handoff" not in out
    path = _transcript(tmp_path, 120_000, nudge.BOUNDARY_TOTAL)
    out, _ = hook("s-bound", path)
    assert "At the next task completion" in out
    assert "/new is ready" in out and "self-slash" not in out
    assert "Do not compact mid-task" in out
    assert hook.state()["s-bound"]["boundary"] is True
    _append(path, _usage(nudge.BOUNDARY_TOTAL + 5_000))
    out, _ = hook("s-bound", path)
    assert "At the next task completion" not in out


def test_boundary_note_survives_compaction(hook, tmp_path):
    """Once per session id: a compaction does not re-arm it, a /new (new id) does."""
    path = _transcript(tmp_path, 50_000, 160_000)
    out, _ = hook("s-once", path)
    assert "At the next task completion" in out
    _append(path, json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
    hook("s-once", path)
    _append(path, _usage(104_000) + _usage(170_000))
    out, _ = hook("s-once", path)
    assert "At the next task completion" not in out
    out, _ = hook("s-new-id", _transcript(tmp_path, 160_000, name="t2.jsonl"))
    assert "At the next task completion" in out


def test_ask_message_at_plus_200k_bare(hook, tmp_path):
    out, pings = hook("s-ask", _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "Context is large" in out
    expected = f"{nudge.AUTO_COMPACT_WINDOW - nudge.AUTO_COMPACT_BUFFER:,}"
    assert f"by itself at about {expected} tokens" in out
    assert "handoff" in out and "/new is ready" in out
    assert "self-slash" not in out
    assert pings == []


def test_ask_message_at_300k_total(hook, tmp_path):
    out, _ = hook("s-total", _transcript(tmp_path, 250_000, nudge.ASK_TOTAL))
    assert "Context is large" in out


@pytest.mark.parametrize("var", ["HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE", "PASEO_AGENT_ID"])
def test_ask_message_in_herdr_or_orca_puts_new_before_compact(hook, tmp_path, monkeypatch, var):
    monkeypatch.setenv(var, "w1:p1")
    out, _ = hook("s-herdr-" + var, _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "Handle it yourself" in out
    assert out.index('self-slash "/new"') < out.index('"/compact <focus>"')
    assert out.index("`handoff` skill") < out.index('"/compact <focus>"')
    assert "must continue in-context" in out
    # The boundary note fires in the same call (total >= 150k) and names self-slash here.
    assert 'the `handoff` skill (its Step 9 runs ~/src/djbclark-ade/bin/self-slash "/new" and queues /baton) instead of /compact' in out
    assert "Do not run /new yourself as well" in out


def test_repeat_ask_every_100k(hook, tmp_path):
    path = _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH)
    hook("s-rep", path)
    _append(path, _usage(46_000 + nudge.ASK_GROWTH + nudge.REPEAT_EVERY - 1))
    out, _ = hook("s-rep", path)
    assert "Context is" not in out
    _append(path, _usage(46_000 + nudge.ASK_GROWTH + nudge.REPEAT_EVERY))
    out, _ = hook("s-rep", path)
    assert "Context is still growing" in out


def test_floor_resets_after_compact_boundary(hook, tmp_path):
    path = _transcript(tmp_path, 50_000, 260_000)
    out, _ = hook("s-floor", path)
    assert "Context is large" in out
    _append(path, json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
    out, _ = hook("s-floor", path)
    assert out == ""
    state = hook.state()["s-floor"]
    assert state["baseline"] is None and state["level"] == 0
    _append(path, _usage(104_000))
    out, _ = hook("s-floor", path)
    assert out == ""
    assert hook.state()["s-floor"]["baseline"] == 104_000
    _append(path, _usage(104_000 + nudge.EARLY_GROWTH))
    out, _ = hook("s-floor", path)
    assert "Context check" in out


def test_shrink_between_prompts_is_a_new_floor(hook, tmp_path):
    path = _transcript(tmp_path, 50_000, 260_000)
    hook("s-shrink", path)
    _append(path, _usage(110_000))  # < 0.75 x 260k, no boundary record seen
    out, _ = hook("s-shrink", path)
    assert out == ""
    assert hook.state()["s-shrink"]["baseline"] == 110_000


def test_page_once_at_plus_300k(hook, tmp_path):
    path = _transcript(tmp_path, 40_000, 40_000 + nudge.PAGE_GROWTH)
    _, pings = hook("s-page", path)
    assert len(pings) == 1
    assert pings[0][0] == str(nudge.PING_BIN)
    assert "/handoff then /new" in pings[0][1]
    _append(path, _usage(40_000 + nudge.PAGE_GROWTH + 10_000))
    _, pings = hook("s-page", path)
    assert pings == []


def test_page_at_400k_total(hook, tmp_path):
    _, pings = hook("s-page-total", _transcript(tmp_path, 350_000, nudge.PAGE_TOTAL))
    assert len(pings) == 1


def test_sidechain_usage_is_ignored(hook, tmp_path):
    path = _transcript(tmp_path, 50_000)
    _append(path, _usage(500_000, isSidechain=True))
    out, pings = hook("s-side", path)
    assert out == ""
    assert pings == []


def test_missing_transcript_path_is_silent_and_safe(hook, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "stdin",
        type("FakeStdin", (), {"read": staticmethod(lambda: json.dumps({"session_id": "s-none"}))})(),
    )
    nudge.main()
    assert capsys.readouterr().out == ""


def test_malformed_stdin_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(nudge, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": staticmethod(lambda: "not json")})())
    nudge.main()  # must not raise


def test_reads_large_transcript_from_tail_only(hook, tmp_path):
    """Real transcripts run tens of MB; the tail read still finds the newest
    usage block, and the head read the session's first one."""
    path = tmp_path / "big.jsonl"
    with path.open("w") as f:
        for _ in range(5000):
            f.write(_usage(1_000))
        f.write(_usage(1_000 + nudge.PAGE_GROWTH))
    out, pings = hook("s-big", path)
    assert "Context is large" in out
    assert len(pings) == 1


# bin/self-slash: --dry-run runs the same gap check a real call does, so the
# refusal is testable without a live pane. The Orca host needs only $ORCA_TERMINAL_HANDLE
# and an `orca` on PATH (never called on a dry run).
_needs_self_slash = pytest.mark.skipif(
    not (shutil.which("orca") and shutil.which("gdate") and shutil.which("ggrep")),
    reason="self-slash dry run needs orca, gdate and ggrep on PATH",
)


def _self_slash(tmp_path, text, handle="th1", log_lines=()):
    log = tmp_path / ".local" / "state" / "self-slash.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    if log_lines:
        log.write_text("".join(line + "\n" for line in log_lines))
    env = {k: v for k, v in os.environ.items()
           if k not in ("HERDR_ENV", "HERDR_PANE_ID", "CURSOR_AGENT", "SELF_SLASH_COMPACT_GAP")}
    env.update(HOME=str(tmp_path), ORCA_TERMINAL_HANDLE=handle)
    return subprocess.run([str(SELF_SLASH), "--dry-run", text], env=env,
                          capture_output=True, text=True, timeout=30)


def _self_slash_paseo(tmp_path, text, agent="ag1"):
    """The Paseo host: $PASEO_AGENT_ID and a CLI path; a dry run never calls the CLI."""
    log = tmp_path / ".local" / "state" / "self-slash.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ("HERDR_ENV", "HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE", "CURSOR_AGENT",
                        "SELF_SLASH_COMPACT_GAP")}
    env.update(HOME=str(tmp_path), PASEO_AGENT_ID=agent, PASEO_CLI="/usr/bin/true")
    return subprocess.run([str(SELF_SLASH), "--dry-run", text], env=env,
                          capture_output=True, text=True, timeout=30)


@pytest.mark.skipif(not (shutil.which("gdate") and shutil.which("ggrep")),
                    reason="self-slash dry run needs gdate and ggrep on PATH")
def test_self_slash_paseo_host_maps_new_to_clear(tmp_path):
    r = _self_slash_paseo(tmp_path, "/new")
    assert r.returncode == 0, r.stderr
    assert "would send to paseo ag1" in r.stdout and ": /clear" in r.stdout
    r = _self_slash_paseo(tmp_path, "/compact keep the open items")
    assert r.returncode == 0, r.stderr
    assert ": /compact keep the open items" in r.stdout


@pytest.mark.skipif(not (shutil.which("gdate") and shutil.which("ggrep")),
                    reason="self-slash dry run needs gdate and ggrep on PATH")
def test_self_slash_paseo_needs_a_cli(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if k not in ("HERDR_ENV", "HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE", "PASEO_CLI")}
    # The script prepends /opt/homebrew/bin to PATH, so a bare PATH cannot hide a real
    # paseo; a non-executable PASEO_CLI is the refusal path.
    env.update(HOME=str(tmp_path), PASEO_AGENT_ID="ag1", PASEO_CLI="/nonexistent/paseo")
    r = subprocess.run([str(SELF_SLASH), "--dry-run", "/compact"], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 3 and "no paseo CLI" in r.stderr


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


@_needs_self_slash
@pytest.mark.parametrize("sent", ["/compact focus", "/new", "/clear", "/reset"])
@pytest.mark.parametrize("text", ["/new", "/compact x", "/clear", "/reset"])
def test_self_slash_refuses_reset_family_within_gap(tmp_path, sent, text):
    r = _self_slash(tmp_path, text, log_lines=[f"{_now()} orca th1: sent {sent}"])
    assert r.returncode == 7, r.stderr
    assert "not sending" in r.stderr


@_needs_self_slash
def test_self_slash_allows_after_gap_other_pane_and_other_commands(tmp_path):
    lines = [f"{_now()} orca th1: sent /new", "2026-01-01 00:00:00 orca th2: sent /compact"]
    assert _self_slash(tmp_path, "/rename foo", log_lines=lines).returncode == 0
    assert _self_slash(tmp_path, "/new", handle="th2").returncode == 0
    assert _self_slash(tmp_path, "/new", handle="th3").returncode == 0


@_needs_self_slash
def test_self_slash_not_sent_lines_do_not_count(tmp_path):
    lines = [f"{_now()} orca th1: NOT sent: /compact was already sent to orca th1 5s ago",
             f"{_now()} orca th1: waiter 123 still queued after 900s; NOT sent: /new"]
    assert _self_slash(tmp_path, "/new", log_lines=lines).returncode == 0


def test_paseo_host_gets_the_finish_note(hook, tmp_path, monkeypatch):
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")
    out, _ = hook("s-paseo", _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "self-slash --finish" in out and "archives this agent" in out
    # the model offers the loose Rule 4 choices; it does not archive itself
    assert "offer the `loose` Rule 4 choices" in out and "rather than archiving yourself" in out
    assert "finish as the last action instead" not in out
    assert 'self-slash "/new" ONCE' in out
    assert "so do not run /new yourself as well" in out


@pytest.mark.parametrize("var", ["HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE"])
def test_finish_note_is_paseo_only(hook, tmp_path, monkeypatch, var):
    monkeypatch.setenv(var, "w1:p1")
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")  # herdr and Orca win in self-slash
    out, _ = hook("s-nofinish-" + var, _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "--finish" not in out
