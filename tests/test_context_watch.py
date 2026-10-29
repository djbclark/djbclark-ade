"""bin/context-watch (2026-10-28): per running Claude Code agent, tokens used vs the real compaction ceiling.
Every test runs the real script as a subprocess against a scratch HOME, a scratch PASEO_HOME and a fake
`paseo` on CONTEXT_WATCH_PASEO; the host's real transcripts, settings and daemon are never read."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "bin" / "context-watch"
ID_A = "aaaaaaaa-1111-4111-8111-111111111111"
ID_B = "bbbbbbbb-2222-4222-8222-222222222222"
ID_C = "cccccccc-3333-4333-8333-333333333333"
SESS_A = "5e5a0000-0000-4000-8000-00000000000a"
SESS_B = "5e5b0000-0000-4000-8000-00000000000b"


def assistant(inp, cache_read=0, cache_create=0, sidechain=False):
    return json.dumps({
        "type": "assistant", "isSidechain": sidechain,
        "message": {"model": "claude-sonnet-5-5", "usage": {
            "input_tokens": inp, "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_create, "output_tokens": 9}}})


class Box:
    def __init__(self, tmp_path):
        self.home = tmp_path / "home"
        (self.home / ".claude" / "projects").mkdir(parents=True)
        self.paseo_home = self.home / ".paseo"
        self.ls = []  # what the fake `paseo ls --json` prints
        self.ls_fails = False
        self.fake = tmp_path / "paseo"

    def settings(self, **kw):
        (self.home / ".claude" / "settings.json").write_text(json.dumps(kw))

    def transcript(self, session, lines, project="-Users-x-src-proj", age=0, raw=None):
        d = self.home / ".claude" / "projects" / project
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{session}.jsonl"
        p.write_text(raw if raw is not None else "\n".join(lines) + "\n")
        if age:
            t = time.time() - age
            os.utime(p, (t, t))
        return p

    def agent(self, agent_id, title, session, provider="claude/claude-sonnet-5-5", state=True):
        self.ls.append({"id": agent_id, "shortId": agent_id[:7], "name": title, "provider": provider,
                        "status": "running", "cwd": "~/src/proj"})
        if state:
            d = self.paseo_home / "agents" / "Users-x-src-proj"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{agent_id}.json").write_text(json.dumps({
                "id": agent_id, "provider": provider.split("/")[0], "cwd": "/Users/x/src/proj",
                "title": title, "persistence": {"sessionId": session}}))

    def run(self, *args):
        body = "#!/bin/sh\n"
        if self.ls_fails:
            body += "echo 'daemon down' >&2\nexit 1\n"
        else:
            body += f"cat <<'EOF'\n{json.dumps(self.ls)}\nEOF\n"
        self.fake.write_text(body)
        self.fake.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PASEO", "CONTEXT_WATCH", "CLAUDE"))}
        env.update(HOME=str(self.home), PASEO_HOME=str(self.paseo_home), CONTEXT_WATCH_PASEO=str(self.fake))
        r = subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env, timeout=30)
        return r


@pytest.fixture()
def box(tmp_path):
    return Box(tmp_path)


def two_agents(box):
    box.settings(autoCompactWindow=300000)
    box.agent(ID_A, "small one", SESS_A)
    box.agent(ID_B, "big one", SESS_B)
    # Sum of the three fields; the newest NON-sidechain block wins over a newer sidechain one.
    box.transcript(SESS_A, [assistant(1000, 50000, 9000), assistant(10, 90000, 3990),
                            assistant(1, 266000, 500, sidechain=True)])
    box.transcript(SESS_B, [assistant(5, 100000, 1000), assistant(14000, 200000, 0)])


def test_lines_sorted_fullest_first_with_wall_distance(box):
    two_agents(box)
    r = box.run()
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "bbbbbbbb big one 214k/267k (80%) wall in 53k",
        "aaaaaaaa small one 94k/267k (35%) wall in 173k",
    ]


def test_json_is_a_list_of_records_sorted_the_same_way(box):
    two_agents(box)
    r = box.run("--json")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert [x["id"] for x in rows] == [ID_B, ID_A]
    top = rows[0]
    assert (top["short_id"], top["title"], top["tokens"], top["ceiling"], top["headroom"], top["pct"]) == (
        "bbbbbbbb", "big one", 214000, 267000, 53000, 80.1)
    assert top["status"] == "ok" and top["session"] == SESS_B and top["source"] == "paseo"


def test_ceiling_follows_autocompactwindow_minus_33k(box):
    box.settings(autoCompactWindow=100000)
    box.agent(ID_A, "x", SESS_A)
    box.transcript(SESS_A, [assistant(1000, 50000, 0)])
    assert box.run().stdout.splitlines() == ["aaaaaaaa x 51k/67k (76%) wall in 16k"]


def test_without_settings_falls_back_to_the_model_window(box):
    box.agent(ID_A, "x", SESS_A)  # no settings.json at all
    box.transcript(SESS_A, [assistant(1000, 50000, 0)])
    # 200k model window - 33k
    assert box.run("--json").stdout and json.loads(box.run("--json").stdout)[0]["ceiling"] == 167000
    box.settings(model="opus[1m]")
    assert json.loads(box.run("--json").stdout)[0]["ceiling"] == 967000


def test_past_the_wall_reads_as_such(box):
    box.settings(autoCompactWindow=300000)
    box.agent(ID_A, "x", SESS_A)
    box.transcript(SESS_A, [assistant(1, 270000, 0)])
    assert box.run().stdout.splitlines() == ["aaaaaaaa x 270k/267k (101%) wall passed by 3k"]


def test_min_pct_hides_the_emptier_agents_and_unknown_ones(box):
    two_agents(box)
    box.agent(ID_C, "gone", "no-such-session")
    r = box.run("--min-pct", "50")
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["bbbbbbbb big one 214k/267k (80%) wall in 53k"]


def test_unreadable_transcript_prints_question_mark_and_exits_0(box):
    two_agents(box)
    box.agent(ID_C, "gone", "no-such-session")
    box.transcript("cafe0000-0000-4000-8000-00000000000c", [], raw="not json\n\x00\xff garbage\n")
    box.agent("dddddddd-4444-4444-8444-444444444444", "garbled", "cafe0000-0000-4000-8000-00000000000c")
    r = box.run()
    assert r.returncode == 0
    lines = r.stdout.splitlines()
    assert lines[:2] == ["bbbbbbbb big one 214k/267k (80%) wall in 53k",
                         "aaaaaaaa small one 94k/267k (35%) wall in 173k"]
    assert sorted(lines[2:]) == ["cccccccc gone ?", "dddddddd garbled ?"]
    rows = {x["id"]: x for x in json.loads(box.run("--json").stdout)}
    assert rows[ID_C]["status"] == "no-transcript" and rows[ID_C]["tokens"] is None


def test_agent_without_a_state_file_is_unknown_not_guessed(box):
    box.settings(autoCompactWindow=300000)
    box.agent(ID_A, "x", SESS_A, state=False)
    box.transcript(SESS_A, [assistant(1, 100000, 0)])  # a newest-in-project guess would find this
    assert box.run().stdout.splitlines() == ["aaaaaaaa x ?"]


def test_only_claude_agents_are_listed(box):
    two_agents(box)
    box.agent(ID_C, "codex one", SESS_A, provider="codex/gpt-6.1-sol")
    assert [x["id"] for x in json.loads(box.run("--json").stdout)] == [ID_B, ID_A]


def test_compact_boundary_after_the_last_usage_is_reported_as_compacted(box):
    box.settings(autoCompactWindow=300000)
    box.agent(ID_A, "x", SESS_A)
    box.transcript(SESS_A, [assistant(1, 260000, 0),
                            json.dumps({"type": "system", "subtype": "compact_boundary"})])
    assert box.run().stdout.splitlines() == ["aaaaaaaa x compacted"]
    assert json.loads(box.run("--json").stdout)[0]["status"] == "compacted"


def test_paseo_down_falls_back_to_transcripts_modified_in_the_last_30_minutes(box):
    box.settings(autoCompactWindow=300000)
    box.ls_fails = True
    box.transcript(SESS_A, [json.dumps({"cwd": "/Users/x/src/proj"}), assistant(1, 100000, 0)], age=60)
    box.transcript(SESS_B, [assistant(1, 200000, 0)], age=31 * 60)  # too old
    r = box.run()
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["5e5a0000 proj 100k/267k (37%) wall in 167k"]
    row = json.loads(box.run("--json").stdout)[0]
    assert row["source"] == "recent" and row["id"] == SESS_A
    assert [x["id"] for x in json.loads(box.run("--json", "--recent-minutes", "60").stdout)] == [SESS_B, SESS_A]


def test_recent_mode_can_be_forced(box):
    box.settings(autoCompactWindow=300000)
    box.agent(ID_A, "paseo one", SESS_A)  # would win in paseo mode
    box.transcript(SESS_A, [assistant(1, 100000, 0)], age=10)
    assert json.loads(box.run("--json", "--source", "recent").stdout)[0]["source"] == "recent"


def test_nothing_running_prints_nothing_and_exits_0(box):
    r = box.run()
    assert (r.returncode, r.stdout) == (0, "")
