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
    box.tool("mcp__jina__read_url", {"url": "https://docs.python.org/3/a?q=1"})
    box.tool("mcp__parallel-search__web_search", {"query": "x"})
    box.tool("Bash", {"command": "~/ops/site-private/bin/web-get https://docs.example.org/p?q=1"})
    assert cats(box) == ["memory"] + ["web"] * 6
    recs = box.records()
    assert [r.get("host") for r in recs][4:] == ["python.org", None, None]          # only allowlisted domains
    assert [r.get("host_class") for r in recs][4:] == ["public", None, "public"]


def test_web_fetch_records_only_an_allowlisted_registrable_domain(box):
    box.tool("WebFetch", {"url": f"https://u:p@Docs.Python.ORG:8443/a/b?token={MARK}#frag", "prompt": "p"})
    box.tool("WebFetch", {"url": f"https://{MARK}host.example.com/a?q=1"})
    first, second = box.records()
    assert first["category"] == "web" and first["host"] == "python.org" and first["host_class"] == "public"
    assert second["host_class"] == "public" and "host" not in second
    assert "/a/b" not in json.dumps(first) and MARK.lower() not in json.dumps(second).lower()


def test_web_failure_is_a_web_event_with_failed_set(box):
    for _ in range(3):
        box.tool("Read", {"file_path": "/nix/store/x/a.py"})
    box.fail("WebFetch", {"url": "https://github.com/x"}, error="timeout")
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
            "quoting_failure", "task_seq", "elapsed_ms", "schema", "classifier_version"}
    for r in recs:
        assert want <= set(r) and set(r) <= want | {"host", "host_class", "path_class", "agent", "dropped"}
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
        ("WebFetch", {"url": f"https://github.com/{MARK}?q={MARK}", "prompt": MARK}),
        ("Bash", {"command": f"web-get 'https://github.com/{MARK}?k={MARK}'"}),
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
    assert b"github.com" in blob                                         # an allowlisted domain is kept


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
    assert time.monotonic() - t0 < 2                                    # the hook deadline
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


# ---- repair round 1 (adversary D1-D10): Bash parsing, web and memory names, subagents, files -----

def cat_of(box, command, **tin):
    box.tool("Bash", {"command": command, **tin})
    return box.records()[-1]["category"]


@pytest.mark.parametrize("command, want", [
    ("rg foo {w}/lib 2>/dev/null", "own_code"),                       # redirect target is not a path
    ("rg foo {w}/lib >/tmp/out 2>&1", "own_code"),
    ("git log --oneline | head -5", "private_other"),                 # pipe filters are not reads
    ("echo hi | wc -l", "private_other"),
    ("cat /nix/store/a/b.py | rg x", "external_code"),                # the first stage is the read
    ("git status && rg foo /nix/store/abc", "external_code"),         # any stage of a compound command
    ("cd /nix/store/abc && cat a.py", "external_code"),               # cd moves the relative paths
    ("cd /tmp/x; ls", "private_other"),
    ("sudo -u root cat /nix/store/a", "external_code"),               # sudo options are not the command
    ("env X=1 FOO=2 rg bar /nix/store/a", "external_code"),
    ("timeout 20 rg bar /nix/store/a", "external_code"),
    ("rg '/usr/bin/env' .", "own_code"),                              # the pattern is not a path
    ("rg -e '/usr/bin' /nix/store/x", "external_code"),
    ("bash -lc 'rg foo /nix/store/x'", "external_code"),
    ("(cd /nix/store/x && rg foo)", "external_code"),
    ("for f in a b; do rg foo /nix/store/x; done", "external_code"),
    ("sed -i s/a/b/ /nix/store/x", "private_other"),                  # an edit, not a read
    ("find /nix/store/x -name '*.py' | head", "external_code"),
    ("cat <<EOF\nrg foo /nix/store/x\nEOF", "own_code"),              # heredoc body is text
    ("echo \"unterminated | rg foo /nix/store/x", "private_other"),  # broken quoting stays safe
])
def test_bash_classification(box, command, want):
    assert cat_of(box, command.format(w=box.work)) == want


@pytest.mark.parametrize("command, want", [
    ("curl -s https://api.github.com/repos/a/b/issues", "web"),
    ("env X=1 curl -sL https://example.org/a | head", "web"),
    ("curl -s http://localhost:18804/mcp", "private_other"),
    ("curl -s http://10.0.0.5/x", "private_other"),
    ("curl -s https://abc.sipb.cloud/x", "private_other"),
    ("gh search code 'foo bar' --limit 5", "web"),
    ("gh api repos/someone/lib/contents/README.md", "web"),
    ("gh api repos/djbclark/djbclark-ade/pulls/5", "private_other"),
    ("gh repo view someone/lib", "web"),
    ("gh pr view 5", "private_other"),
    ("ssh h 'curl https://example.org/a'", "private_other"),         # the agent did not fetch it
])
def test_bash_web_lookups(box, command, want):
    assert cat_of(box, command) == want


@pytest.mark.parametrize("tool, want", [
    ("mcp__claude_ai_Exa__web_search_exa", "web"),
    ("mcp__claude_ai_Firecrawl__firecrawl_search", "web"),
    ("mcp__claude_ai_Context7__query-docs", "web"),
    ("mcp__context7__get-library-docs", "web"),
    ("mcp__deepwiki__ask_question", "web"),
    ("mcp__plugin_context7_context7__query-docs", "web"),
    ("mcp__github__search_code", "web"),
    ("mcp__github__create_issue", "private_other"),
    ("mcp__claude_ai_Gmail__search_threads", "private_other"),
    ("mcp__basic-memory__search_notes", "memory"),
    ("mcp__claude_ai_Basic_Memory__read_note", "memory"),
    ("mcp__graft__ask", "own_code"),
])
def test_mcp_servers_are_classified_by_server_name(box, tool, want):
    box.tool(tool, {"query": "q"})
    assert cats(box) == [want]


def test_memory_files_are_memory_reads(box):
    h = box.home
    box.tool("Read", {"file_path": f"{h}/ops/site-private/memory/feedback_x.md"})
    box.tool("Read", {"file_path": f"{h}/.claude/projects/-Users-x/memory/MEMORY.md"})
    box.tool("Bash", {"command": f"rg foo {h}/ops/site-private/memory 2>/dev/null"})
    box.tool("Bash", {"command": "cat ~/.agents/AGENTS.md"})
    box.tool("Read", {"file_path": f"{h}/ops/site-private/bin/tool"})
    assert cats(box) == ["memory"] * 4 + ["own_code"]
    assert [r.get("path_class") for r in box.records()] == ["memory"] * 4 + ["ops"]


def test_memory_and_web_events_feed_the_run_counters(box):
    box.tool("Read", {"file_path": "/nix/store/x/a.py"})
    box.tool("Bash", {"command": "gh search code foo"})
    box.tool("Bash", {"command": "cat /nix/store/x/b.py 2>/dev/null | head"})
    recs = box.records()
    assert [r["run_length"] for r in recs] == [1, 0, 1]
    assert [r["web_or_memory_before"] for r in recs] == [False, False, True]


def test_path_class_is_a_fixed_enum(box):
    h = box.home
    for p in (f"{box.work}/a.py", f"{h}/src/other/a.py", f"{h}/ops/x/a.py", "/nix/store/x/a.py",
              f"{h}/.cache/x/a.py", f"{h}/.local/state/x", "/tmp/x", f"{h}/Downloads/x", "/etc/hosts"):
        box.tool("Read", {"file_path": p})
    assert [r["path_class"] for r in box.records()] == [
        "cwd", "src", "ops", "nix", "cache", "state", "tmp", "home", "other"]
    assert all("path_top" not in r for r in box.records())


# ---- subagents --------------------------------------------------------------------------------

def test_subagents_do_not_share_carry_over_state(box):
    def sub(name, tin, agent, **kw):
        return box.tool(name, tin, agent_id=agent, **kw)
    sub("Read", {"file_path": "/nix/store/x/a1"}, "agent-A")
    sub("Read", {"file_path": "/nix/store/x/a2"}, "agent-A")
    sub("WebSearch", {"query": "q"}, "agent-B")                         # B's web search...
    sub("Read", {"file_path": "/nix/store/x/a3"}, "agent-A")            # ...is not A's
    sub("Read", {"file_path": str(box.work / "own")}, "agent-B")        # B's own-code read resets B only
    sub("Read", {"file_path": "/nix/store/x/a4"}, "agent-A")
    box.tool("Read", {"file_path": "/nix/store/x/m1"})                  # the main agent, no agent_id
    recs = box.records()
    assert [r["run_length"] for r in recs] == [1, 2, 0, 3, 0, 4, 1]
    assert [r["web_or_memory_before"] for r in recs] == [False] * 4 + [True] + [False] * 2   # only B saw the web
    assert [r["duplicate"] for r in recs] == [False] * 7
    agents = [r.get("agent") for r in recs]
    assert agents[0] == agents[1] == agents[3] == agents[5] and agents[2] == agents[4]
    assert agents[0] != agents[2] and agents[6] is None and len(agents[0]) == 8
    assert "agent-A" not in json.dumps(recs)


def test_subagent_state_is_keyed_by_agent_and_inherits_the_task(box):
    box.tool("Read", {"file_path": "/tmp/a"})
    box.prompt()
    box.prompt()
    box.tool("Read", {"file_path": "/tmp/a"}, agent_id="agent-A")
    box.tool("Read", {"file_path": "/tmp/a"}, agent_id="agent-A", advance=5)
    box.tool("Read", {"file_path": "/tmp/a"}, agent_id="agent-B", advance=5)
    recs = box.records()
    assert [r["task_seq"] for r in recs[3:]] == [2, 2, 2]
    assert recs[4]["elapsed_ms"] == 5000 and recs[3]["elapsed_ms"] is None
    assert recs[5]["elapsed_ms"] is None                                # B's first event: nothing before it
    assert len(list(box.state.glob("*.state.json"))) == 3


def test_missing_or_odd_agent_id_means_the_main_agent(box):
    for aid in (None, "", 7, ["x"]):
        box.tool("Read", {"file_path": "/tmp/a"}, agent_id=aid)
    assert all("agent" not in r for r in box.records())
    assert [r["duplicate"] for r in box.records()] == [False, True, True, True]


# ---- privacy of names -------------------------------------------------------------------------

@pytest.mark.parametrize("url, klass, host", [
    ("http://localhost:18804/mcp", "loopback", None),
    ("http://127.0.0.1/x", "loopback", None),
    ("http://[::1]:80/x", "loopback", None),
    ("https://10.0.0.5/", "private_ip", None),
    ("https://192.168.1.2:8443/", "private_ip", None),
    ("https://[2001:db8::1]/x", "private_ip", None),                   # documentation range: not global
    ("https://8.8.8.8/x", "public", None),
    ("https://myhost/x", "internal", None),
    ("https://abc.sipb.cloud/x", "internal", None),
    ("https://printer.local/x", "internal", None),
    ("https://" + MARK + "capability.example.com/x", "public", None),
    ("https://docs.python.org/3/", "public", "python.org"),
    ("https://GitHub.com./a", "public", "github.com"),
    ("https://u:p@raw.githubusercontent.com:8443/a?q=1", "public", "githubusercontent.com"),
    ("https://www.example.co.uk/x", "public", None),
    ("https://[::1", "invalid", None),
    ("notaurl", "invalid", None),
])
def test_url_host_is_bucketed_never_stored_verbatim(box, url, klass, host):
    box.tool("WebFetch", {"url": url})
    (rec,) = box.records()
    assert rec["host_class"] == klass and rec.get("host") == host
    assert MARK.lower() not in json.dumps(rec).lower()


def test_unknown_names_are_bucketed(box):
    box.tool("mcp__SECRETMARK25__x", {})
    box.tool("mcp__claude_ai_SECRETMARK_memory__x", {})                # matches a kind by suffix only
    box.tool("mcp__firecrawl__firecrawl_search", {"query": "q"})
    box.tool("mcp__claude_ai_Exa__web_search_exa", {"query": "q"})
    box.tool("SECRETMARKTool", {})
    box.tool("Read", {"file_path": "/tmp/a"}, model="SECRETMARK-model")
    box.tool("Read", {"file_path": "/tmp/a"}, model="claude-opus-5-5")
    recs = box.records()
    assert [r["tool"] for r in recs[:5]] == [
        "mcp__other", "mcp__memory_server", "mcp__firecrawl__firecrawl_search",
        "mcp__claude_ai_exa__web_search_exa", "other"]
    assert [r["client"] for r in recs[5:]] == ["claude-code", "claude-opus-5-5"]
    assert MARK.lower() not in b"".join(p.read_bytes() for p in box.state.iterdir()).decode().lower()


def test_records_carry_a_schema_and_classifier_version(box):
    box.tool("Read", {"file_path": "/tmp/a"})
    box.prompt()
    assert all(r["schema"] == 2 and r["classifier_version"] == 2 for r in box.records())


def test_call_hashes_are_salted_per_session(box):
    import hashlib
    box.tool("Bash", {"command": "git status"})
    st = json.loads((box.state / f"{SID}.state.json").read_text())
    bare = hashlib.sha256(("Bash" + json.dumps({"command": "git status"}, sort_keys=True)).encode()).hexdigest()[:12]
    assert st["recent"] and bare not in st["recent"]
    box.run({"tool_name": "Bash", "tool_input": {"command": "git status"}}, sid="other")
    other = json.loads((box.state / "other.state.json").read_text())
    assert other["recent"] != st["recent"] and other["salt"] != st["salt"]


# ---- hostile files (D5) -----------------------------------------------------------------------

def test_planted_symlinks_are_not_followed(box, tmp_path):
    box.tool("Read", {"file_path": "/tmp/a"})                         # creates the three files
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\n")
    for suffix in ("jsonl", "lock", "state.json"):
        f = box.state / f"{SID}.{suffix}"
        f.unlink()
        f.symlink_to(victim)
    box.tool("Read", {"file_path": "/tmp/b"})
    box.tool("Read", {"file_path": "/tmp/c"})
    assert victim.read_text() == "keep\n"


def test_planted_state_symlink_cannot_switch_recording_off(box, tmp_path):
    box.tool("Read", {"file_path": "/tmp/a"})
    target = tmp_path / "capped.json"
    target.write_text('{"capped":true}')
    (box.state / f"{SID}.state.json").unlink()
    (box.state / f"{SID}.state.json").symlink_to(target)
    box.tool("Read", {"file_path": "/tmp/b"})
    assert len(box.records()) == 2 and target.read_text() == '{"capped":true}'


@pytest.mark.parametrize("suffix", ["jsonl", "lock", "state.json"])
def test_fifo_in_place_of_a_file_never_blocks_the_hook(box, suffix):
    box.tool("Read", {"file_path": "/tmp/a"})
    f = box.state / f"{SID}.{suffix}"
    f.unlink()
    os.mkfifo(f)
    t0 = time.monotonic()
    box.tool("Read", {"file_path": "/tmp/b"})
    assert time.monotonic() - t0 < 2


def test_existing_state_dir_is_tightened_to_0700(box):
    box.state.mkdir(mode=0o755)
    box.state.chmod(0o755)
    box.tool("Read", {"file_path": "/tmp/a"})
    assert stat.S_IMODE(box.state.stat().st_mode) == 0o700 and len(box.records()) == 1


def test_state_dir_that_is_a_symlink_is_refused(box, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    box.state.symlink_to(real)
    box.tool("Read", {"file_path": "/tmp/a"})
    assert list(real.iterdir()) == []


# ---- pruning (D8) and dropped events (D9) -----------------------------------------------------

def test_prune_removes_old_files_once_a_day_and_keeps_the_rest(box):
    box.tool("Read", {"file_path": "/tmp/a"})
    day = 86_400
    fresh_old = {}
    for name in ("old.jsonl", "old.state.json", "old.lock", "old.aXXXX.drops", ".st-leftover", f"{SID}.zzz.state.json"):
        p = box.state / name
        p.write_text("x")
        os.utime(p, (box.clock - 40 * day, box.clock - 40 * day))
        fresh_old[name] = p
    young = box.state / "young.jsonl"
    young.write_text("x")
    os.utime(young, (box.clock - 3 * day, box.clock - 3 * day))
    unrelated = box.state / "notes.txt"
    unrelated.write_text("x")
    os.utime(unrelated, (box.clock - 90 * day, box.clock - 90 * day))
    box.prompt()
    left = {p.name for p in box.state.iterdir()}
    assert not {"old.jsonl", "old.state.json", "old.lock", "old.aXXXX.drops", ".st-leftover"} & left
    assert {"young.jsonl", "notes.txt", f"{SID}.jsonl", f"{SID}.zzz.state.json", ".prune-stamp"} <= left
    again = box.state / "again.jsonl"                                  # a second prompt the same day: no scan
    again.write_text("x")
    os.utime(again, (box.clock - 40 * day, box.clock - 40 * day))
    box.prompt()
    assert again.exists()
    box.prompt(advance=2 * day)
    assert not again.exists()


def test_prune_never_follows_symlinks_and_honours_the_retention_setting(box, tmp_path):
    box.tool("Read", {"file_path": "/tmp/a"})
    outside = tmp_path / "outside.jsonl"
    outside.write_text("x")
    link = box.state / "old.jsonl"
    link.symlink_to(outside)
    os.utime(link, (box.clock - 99 * 86_400,) * 2, follow_symlinks=False)
    short = box.state / "short.jsonl"
    short.write_text("x")
    os.utime(short, (box.clock - 2 * 86_400,) * 2)
    box.run({"hook_event_name": "UserPromptSubmit", "prompt": "p"}, PRIOR_ART_RETENTION_DAYS="1")
    assert outside.exists() and not short.exists()


def test_events_lost_to_a_held_lock_are_counted_in_the_next_record(box):
    import fcntl
    box.tool("Read", {"file_path": "/tmp/a"})
    fd = os.open(box.state / f"{SID}.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        box.tool("Read", {"file_path": "/tmp/b"})
        box.tool("Read", {"file_path": "/tmp/c"})
    finally:
        os.close(fd)
    assert len(box.records()) == 1
    box.tool("Read", {"file_path": "/tmp/d"})
    box.tool("Read", {"file_path": "/tmp/e"})
    recs = box.records()
    assert [r.get("dropped") for r in recs] == [None, 2, None]
