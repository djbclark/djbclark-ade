"""claude/hooks/prior_art_nudge.py (2026-10-26, slice D2): shadow telemetry only. It records one JSON line
per tool event (category, byte counts, run and duplicate flags) and must never print, block or write a
raw command, path, query, URL or output. Every test runs the real script as a subprocess against a
scratch HOME and a scratch PRIOR_ART_STATE."""
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "claude" / "hooks" / "prior_art_nudge.py"
MARK = "SECRETMARK"
SID = "sess-1"


class Box:
    def __init__(self, tmp_path):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.work = self.home / "src" / "proj"
        self.work.mkdir(parents=True)
        self.state = tmp_path / "state"
        self.clock = 1_800_000_000.0

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PRIOR_ART", "CLAUDE"))}
        env.update(HOME=str(self.home), PRIOR_ART_STATE=str(self.state),
                   PRIOR_ART_NOW=str(self.clock))
        env.update(extra)
        return env

    def run(self, event, sid=SID, advance=1.0, raw=None, **extra):
        """Run the hook once; the exit status is 0 and stdout and stderr are empty, always."""
        self.clock += advance
        if raw is None:
            event = {"session_id": sid, "cwd": str(self.work), "hook_event_name": "PostToolUse", **event}
            raw = json.dumps(event).encode()
        r = subprocess.run([sys.executable, str(HOOK)], input=raw, capture_output=True,
                           timeout=30, env=self.env(**extra))
        assert r.returncode == 0, r.stderr
        assert r.stdout == b"" and r.stderr == b""
        return r

    def tool(self, name, tool_input=None, response="", advance=1.0, **event):
        return self.run({"tool_name": name, "tool_input": tool_input or {}, "tool_response": response,
                         **event}, advance=advance)

    def fail(self, name, tool_input=None, error="boom"):
        return self.run({"hook_event_name": "PostToolUseFailure", "tool_name": name,
                         "tool_input": tool_input or {}, "error": error})

    def prompt(self, text="do a thing", **kw):
        return self.run({"hook_event_name": "UserPromptSubmit", "prompt": text}, **kw)

    def records(self, sid=SID):
        f = self.state / f"{sid}.jsonl"
        return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


def cats(box):
    return [r["category"] for r in box.records()]


# ---- classification -------------------------------------------------------------------------

def test_own_code_read_is_own_code(box):
    box.tool("Read", {"file_path": str(box.work / "a.py")}, "x" * 400)
    box.tool("Grep", {"pattern": "foo"})                              # no path: the session cwd
    box.tool("Bash", {"command": f"rg foo {box.home}/ops/site-private/bin"})
    assert cats(box) == ["own_code"] * 3
    first = box.records()[0]
    assert first["bytes"] == 400 and first["tokens_est"] == 100 and first["run_length"] == 0


@pytest.mark.parametrize("path", [
    "{home}/src/proj/node_modules/left-pad/index.js",
    "{home}/.venv/lib/python3.13/site-packages/requests/api.py",
    "{home}/.cargo/registry/src/index/serde-1.0/src/lib.rs",
    "{home}/.cache/uv/archive/abc/x.py",
    "/nix/store/abc-foo/lib/x.py",
    "{home}/src/proj/vendor/lib/x.go",
])
def test_external_tree_read_is_external_code(box, path):
    box.tool("Read", {"file_path": path.format(home=box.home)})
    assert cats(box) == ["external_code"]


def test_shell_read_of_external_tree_is_external_code(box):
    box.tool("Bash", {"command": "cd x && rg -n parse node_modules/yaml/dist | head -20"})
    box.tool("Bash", {"command": f"cat {box.home}/.cache/foo/bar.py"})
    assert cats(box) == ["external_code"] * 2


def test_private_or_other_paths_and_commands(box):
    box.tool("Read", {"file_path": "/tmp/elsewhere/notes.txt"})
    box.tool("Bash", {"command": "git status"})
    box.tool("Edit", {"file_path": str(box.work / "a.py")})
    assert cats(box) == ["private_other"] * 3


def test_memory_and_web_tools(box):
    box.tool("mcp__basic-memory__search_notes", {"query": "x"})
    box.tool("WebSearch", {"query": "x"})
    box.tool("mcp__firecrawl__firecrawl_search", {"query": "x"})
    box.tool("mcp__exa__web_search_exa", {"query": "x"})
    box.tool("mcp__jina__read_url", {"url": "https://jina.example/a?q=1"})
    box.tool("mcp__parallel-search__web_search", {"query": "x"})
    box.tool("Bash", {"command": "~/ops/site-private/bin/web-get https://docs.example.org/p?q=1"})
    assert cats(box) == ["memory"] + ["web"] * 6
    hosts = [r.get("host") for r in box.records()]
    assert hosts[4:] == ["jina.example", None, "docs.example.org"]


def test_web_fetch_records_only_the_host(box):
    box.tool("WebFetch", {"url": f"https://Docs.Example.com:8443/a/b?token={MARK}#frag", "prompt": "p"})
    (rec,) = box.records()
    assert rec["category"] == "web" and rec["host"] == "docs.example.com"
    assert "/a/b" not in json.dumps(rec)


def test_web_failure_is_a_web_event_with_failed_set(box):
    for _ in range(3):
        box.tool("Read", {"file_path": "/nix/store/x/a.py"})
    box.fail("WebFetch", {"url": "https://example.com/x"}, error="timeout")
    box.tool("Read", {"file_path": "/nix/store/x/b.py"})
    recs = box.records()
    assert recs[3]["category"] == "web" and recs[3]["failed"] is True
    assert recs[3]["bytes"] == len("timeout") and recs[3]["run_length"] == 0
    assert recs[4]["web_or_memory_before"] is True and recs[4]["run_length"] == 1


# ---- runs, duplicates, retries, quoting failures, task change --------------------------------

def test_external_run_counts_consecutive_reads_and_resets(box):
    for n in range(4):
        box.tool("Read", {"file_path": f"/nix/store/x/f{n}.py"})
    box.tool("Read", {"file_path": str(box.work / "mine.py")})          # own code breaks the run
    box.tool("Read", {"file_path": "/nix/store/x/g.py"})
    box.tool("Edit", {"file_path": str(box.work / "mine.py")})          # a neutral event keeps it
    box.tool("Read", {"file_path": "/nix/store/x/h.py"})
    assert [r["run_length"] for r in box.records()] == [1, 2, 3, 4, 0, 1, 1, 2]
    assert [r["external_run"] for r in box.records()] == [False, False, True, True] + [False] * 4
    assert [r["web_or_memory_before"] for r in box.records()] == [False] * 8


def test_memory_hit_resets_run_and_is_remembered(box):
    box.tool("Read", {"file_path": "/nix/store/x/a.py"})
    box.tool("mcp__basic-memory__read_note", {"identifier": "x"})
    box.tool("Read", {"file_path": "/nix/store/x/b.py"})
    recs = box.records()
    assert [r["run_length"] for r in recs] == [1, 0, 1]
    assert [r["web_or_memory_before"] for r in recs] == [False, False, True]


def test_task_change_by_prompt_resets_counters(box):
    box.tool("Read", {"file_path": "/nix/store/x/a.py"})
    box.tool("WebSearch", {"query": "x"})
    box.tool("Read", {"file_path": "/nix/store/x/a.py"})
    box.prompt()
    box.tool("Read", {"file_path": "/nix/store/x/a.py"})                # not a duplicate: new task
    recs = box.records()
    assert recs[3]["category"] == "task_change" and recs[3]["event"] == "UserPromptSubmit"
    assert recs[4]["run_length"] == 1 and recs[4]["web_or_memory_before"] is False
    assert recs[4]["duplicate"] is False
    assert [r["task_seq"] for r in recs] == [0, 0, 0, 1, 1]


def test_long_idle_gap_is_a_task_change(box):
    box.tool("WebSearch", {"query": "x"})
    box.tool("Read", {"file_path": "/nix/store/x/a.py"}, advance=3600)
    box.tool("Read", {"file_path": "/nix/store/x/b.py"}, advance=5)
    recs = box.records()
    assert [r["task_seq"] for r in recs] == [0, 1, 1]
    assert recs[1]["web_or_memory_before"] is False and recs[1]["elapsed_ms"] == 3_600_000
    assert recs[2]["elapsed_ms"] == 5000 and recs[2]["run_length"] == 2


def test_duplicate_calls_are_flagged_after_the_first(box):
    box.tool("Read", {"file_path": "/nix/store/x/a.py"}, "one")
    box.tool("Read", {"file_path": "/nix/store/x/b.py"})
    box.tool("Read", {"file_path": "/nix/store/x/a.py"}, "one")
    box.tool("Grep", {"pattern": "p", "path": "/nix/store/x/a.py"})     # same path, other tool
    assert [r["duplicate"] for r in box.records()] == [False, False, True, False]


def test_quoting_failure_needs_a_failed_shell_command_with_a_marker(box):
    cmd = {"command": "ssh h 'echo \"x'"}
    box.fail("Bash", cmd, error="Exit 2\nbash: -c: line 1: unexpected EOF while looking for matching `\"'")
    box.fail("Bash", {"command": "false"}, error="Exit code 1")
    box.fail("Bash", {"command": "sh -c 'if'"}, error="sh: syntax error near unexpected token")
    box.tool("Bash", {"command": "echo unterminated"}, "unterminated string in docs")   # not a failure
    box.fail("Read", {"file_path": "/tmp/f"}, error="unterminated")                        # not a shell tool
    assert [r["quoting_failure"] for r in box.records()] == [True, False, True, False, False]


def test_retry_is_the_same_call_right_after_its_failure(box):
    cmd = {"command": "make build"}
    box.fail("Bash", cmd)
    box.tool("Bash", cmd)                                               # retry; succeeded
    box.tool("Bash", cmd)                                               # a duplicate, not a retry
    box.fail("Bash", {"command": "make test"})
    box.tool("Bash", {"command": "make lint"})
    box.tool("Bash", {"command": "make test"})                          # a failure was not the last event
    assert [r["retry"] for r in box.records()] == [False, True, False, False, False, False]
    assert [r["duplicate"] for r in box.records()] == [False, True, True, False, False, True]


def test_failure_detected_from_an_exit_code_in_the_response(box):
    box.tool("Bash", {"command": "x"}, {"stdout": "", "stderr": "syntax error", "exit_code": 2})
    box.tool("Bash", {"command": "y"}, {"stdout": "ok", "stderr": "", "exit_code": 0})
    recs = box.records()
    assert (recs[0]["failed"], recs[0]["quoting_failure"]) == (True, True)
    assert (recs[1]["failed"], recs[1]["quoting_failure"]) == (False, False)


def test_output_size_counts_utf8_bytes_of_every_text_leaf(box):
    box.tool("Bash", {"command": "ls"}, {"stdout": "é" * 100, "stderr": "e" * 40})
    box.tool("mcp__exa__web_search_exa", {"query": "q"}, [{"type": "text", "text": "a" * 80}, {"x": ["b" * 20]}])
    recs = box.records()
    assert (recs[0]["bytes"], recs[0]["tokens_est"]) == (240, 60)
    assert recs[1]["bytes"] == 100


def test_model_string_and_session_pseudonym(box):
    box.tool("Read", {"file_path": "/tmp/a"}, model="claude-sonnet-5-5")
    box.tool("Read", {"file_path": "/tmp/a"})
    a, b = box.records()
    assert a["client"] == "claude-sonnet-5-5" and b["client"] == "claude-code"
    assert len(a["session"]) == 12 and a["session"] == b["session"] and SID not in a["session"]
    assert a["elapsed_ms"] is None and b["elapsed_ms"] == 1000


# ---- acceptance: exactly one record per event, silent, private, bounded --------------------------

def test_exactly_one_record_per_event_with_fixed_fields(box):
    events = [("Read", {"file_path": "/nix/store/x/a.py"}), ("WebSearch", {"query": "q"}),
              ("Bash", {"command": "ls"}), ("Read", {"file_path": str(box.work / "z")})]
    for name, tin in events:
        box.tool(name, tin)
    box.prompt()
    box.fail("Bash", {"command": "x"})
    recs = box.records()
    assert len(recs) == len(events) + 2
    want = {"ts", "session", "event", "client", "tool", "category", "failed", "bytes", "tokens_est",
            "web_or_memory_before", "run_length", "external_run", "duplicate", "retry",
            "quoting_failure", "task_seq", "elapsed_ms"}
    for r in recs:
        assert want <= set(r) and set(r) <= want | {"host", "path_top"}
        assert r["ts"].endswith("+00:00")


def test_no_raw_private_text_reaches_any_state_file(box):
    secret_dir = box.home / f"{MARK}dir"
    tin_paths = [
        ("Bash", {"command": f"rg {MARK} {secret_dir}/{MARK}.py && echo {MARK}"}),
        ("Read", {"file_path": f"{secret_dir}/{MARK}.txt"}),
        ("Grep", {"pattern": MARK, "path": str(secret_dir)}),
        ("Glob", {"pattern": f"/{MARK}/**/*.py"}),
        ("WebSearch", {"query": f"{MARK} private query"}),
        ("mcp__firecrawl__firecrawl_search", {"query": MARK}),
        ("mcp__basic-memory__search_notes", {"query": MARK}),
        ("WebFetch", {"url": f"https://example.com/{MARK}?q={MARK}", "prompt": MARK}),
        ("Bash", {"command": f"web-get 'https://example.com/{MARK}?k={MARK}'"}),
        ("Bash", {"command": f"ssh {MARK} 'echo \"{MARK}'"}),
    ]
    for name, tin in tin_paths:
        box.tool(name, tin, {"stdout": MARK * 5, "content": [{"text": MARK}]}, cwd=str(secret_dir))
    box.fail("Bash", {"command": MARK}, error=f"syntax error {MARK}")
    box.prompt(text=f"please {MARK}")
    box.run({"tool_name": "Read", "tool_input": {"file_path": f"/{MARK}/a"}, "tool_response": MARK})
    blob = b"".join(p.read_bytes() for p in box.state.iterdir())
    assert blob and MARK.encode() not in blob
    assert len(box.records()) == len(tin_paths) + 3
    assert b"example.com" in blob                                        # the host name is allowed


def test_modes_are_private(box):
    box.tool("Read", {"file_path": "/tmp/a"})
    assert stat.S_IMODE(box.state.stat().st_mode) == 0o700
    assert stat.S_IMODE((box.state / f"{SID}.jsonl").stat().st_mode) == 0o600
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in box.state.iterdir())


def test_shadow_switch_off_records_nothing(box):
    box.run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/a"}}, PRIOR_ART_SHADOW="0")
    assert not box.state.exists()
    box.run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/a"}}, PRIOR_ART_SHADOW="1")
    assert len(box.records()) == 1


def test_session_id_cannot_escape_the_state_dir(box):
    box.run({"tool_name": "Read", "tool_input": {}}, sid="../../evil/x y")
    assert len(list(box.state.glob("*.jsonl"))) == 1
    assert not (box.state.parent / "evil").exists() and not (box.state.parent.parent / "evil").exists()


def test_missing_transcript_path_is_irrelevant(box):
    box.tool("Read", {"file_path": "/tmp/a"}, transcript_path="/nonexistent/t.jsonl")
    assert cats(box) == ["private_other"]


def huge_nesting(depth):
    return ("[" * depth).encode()


@pytest.mark.parametrize("raw", [
    b"", b"not json", b"[]", b"null", b"123", b'"x"', b"{", b'{"tool_name": ',
    huge_nesting(200_000),
    b'{"tool_name":"Read","tool_input":' + huge_nesting(50_000) + b"}",
    b'{"tool_name":"Read","tool_input":"notadict","tool_response":null,"session_id":["x"]}',
    b'{"tool_name":["Read"],"tool_input":[1],"cwd":5,"model":{"a":1}}',
    b'{"tool_name":"Read","tool_input":{"file_path":"/tmp/a"},"tool_response":"ok"}\xff\xfe\x80garbage',
    b'{"tool_name":"Read","tool_response":"bad \xff tail"}',
    b'{"tool_name":"Bash","tool_input":{"command":["bash","-lc"]},"error":"x"}\n{"second":1}',
])
def test_malformed_events_exit_silently(box, raw):
    box.run(None, raw=raw)


def test_unwritable_state_dir_is_silent(box, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a dir")
    box.state = blocker / "sub"
    box.run({"tool_name": "Read", "tool_input": {}})
    ro = tmp_path / "ro"
    ro.mkdir(mode=0o500)
    box.state = ro / "state"
    try:
        box.run({"tool_name": "Read", "tool_input": {}})
        assert not box.state.exists()
    finally:
        ro.chmod(0o700)


def test_five_megabyte_payload_finishes_within_the_deadline_and_counts_bytes(box):
    big = "é" * (2_600_000)                                             # 5.2 MB of UTF-8
    t0 = time.monotonic()
    box.tool("Bash", {"command": "cat big"}, {"stdout": big, "stderr": ""})
    assert time.monotonic() - t0 < 4
    (rec,) = box.records()
    assert rec["bytes"] == 5_200_000 and rec["tokens_est"] == 1_300_000


def test_file_is_capped_at_five_megabytes(box):
    cap = 5 * 1024 * 1024
    box.tool("Read", {"file_path": "/tmp/a"})
    f = box.state / f"{SID}.jsonl"
    room = cap - 700 - f.stat().st_size                                  # a record is ~330 bytes
    with f.open("ab") as fh:
        fh.write(b'{"filler":"' + b"x" * (room - 14) + b'"}\n')
    assert f.stat().st_size == cap - 700
    for _ in range(4):
        box.tool("Read", {"file_path": "/tmp/a"})
    before = f.stat().st_size
    lines = f.read_bytes().splitlines()
    assert before <= cap and 2 <= sum(b'"category"' in ln for ln in lines) <= 3   # some fit, then the cap
    assert lines.count(b'{"capped":true}') == 1 and lines[-1] == b'{"capped":true}'
    for _ in range(2):
        box.tool("Read", {"file_path": "/tmp/a"})
    assert f.stat().st_size == before


def test_parallel_events_each_leave_exactly_one_record(box):
    procs = [subprocess.Popen([sys.executable, str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=box.env()) for _ in range(12)]
    for n, p in enumerate(procs):
        p.stdin.write(json.dumps({"session_id": SID, "tool_name": "Read", "cwd": str(box.work),
                                  "tool_input": {"file_path": f"/nix/store/x/{n}.py"}}).encode())
        p.stdin.close()
    for p in procs:
        assert p.wait(timeout=30) == 0
        assert p.stdout.read() == b"" and p.stderr.read() == b""
    recs = box.records()
    assert len(recs) == 12 and sorted(r["run_length"] for r in recs) == list(range(1, 13))
