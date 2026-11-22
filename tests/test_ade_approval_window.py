"""bin/ade_approval_window.py, bin/ade-approval-window and claude/hooks/approval_window_permit.py (2026-11-22).

Nothing here touches the real grant file, daemon or audit log: every test passes its own grant path, daemon and log
through function parameters. The daemon is faked in two ways: an in-process object with the same two methods (the
responder tests) and an HTTP opener that answers Paseo's Agent MCP JSON-RPC (the wire tests, no socket is opened)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
sys.path.insert(0, str(REPO / "claude" / "hooks"))
import ade_approval_window as W  # noqa: E402
import approval_window_permit as HOOK  # noqa: E402

NOW = 1_800_000_000.0   # a fixed clock
HOME = "/Users/tester"
UID = os.getuid()
AGENT = "11111111-1111-4111-8111-111111111111"
NONCE = "0123456789abcdef0123456789abcdef"


def iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def write_grant(tmp_path: Path, *, granted=NOW - 10, duration=3600, expires=None, extra=None, raw=None, mode=0o644,
                dir_mode=0o755) -> str:
    d = tmp_path / "var-db-sudo-ask"
    d.mkdir(exist_ok=True)
    os.chmod(d, dir_mode)
    path = d / "grant"
    if raw is None:
        body = {"expires_utc": iso(expires if expires is not None else granted + duration), "granted_utc": iso(granted),
                "granted_by_uid": 501, "duration_s": duration, "nonce": NONCE}
        body.update(extra or {})
        raw = json.dumps(body)
    path.write_text(raw)
    os.chmod(path, mode)
    return str(path)


def window(path: str, now: float = NOW, owner_uid: int = UID) -> W.Window:
    return W.read_window(path, now, owner_uid)


# ---------------------------------------------------------------- the checker


def test_open_window(tmp_path):
    w = window(write_grant(tmp_path))
    assert w.open and w.remaining_s == 3590 and w.expires_epoch == NOW - 10 + 3600
    assert W.window_open(write_grant(tmp_path), NOW, UID) is True


def test_expired_window_is_closed(tmp_path):
    w = window(write_grant(tmp_path, granted=NOW - 3700, duration=3600))
    assert not w.open and "expired" in w.reason


def test_far_future_grant_is_tampering(tmp_path):
    # granted inside the clock slack, 24 h long: it expires 100 s further out than any real grant can
    w = window(write_grant(tmp_path, granted=NOW + 100, duration=86400))
    assert not w.open and "24h" in w.reason


def test_a_month_long_grant_is_closed(tmp_path):
    assert not window(write_grant(tmp_path, granted=NOW - 10, duration=30 * 86400)).open


def test_a_24h_window_is_open(tmp_path):
    assert window(write_grant(tmp_path, granted=NOW - 5, duration=86400)).open


def test_wrong_owner_is_closed(tmp_path):
    if UID == 0:
        pytest.skip("the test user is root")
    w = W.read_window(write_grant(tmp_path), NOW)         # production owner: uid 0
    assert not w.open and "root-owned" in w.reason


@pytest.mark.parametrize("mode", [0o664, 0o666, 0o646, 0o620])
def test_writable_file_is_closed(tmp_path, mode):
    assert not window(write_grant(tmp_path, mode=mode)).open


@pytest.mark.parametrize("dir_mode", [0o775, 0o777, 0o757])
def test_writable_dir_is_closed(tmp_path, dir_mode):
    assert not window(write_grant(tmp_path, dir_mode=dir_mode)).open


def test_symlinked_file_is_closed(tmp_path):
    real = write_grant(tmp_path)
    link = tmp_path / "linkdir"
    link.mkdir()
    os.chmod(link, 0o755)
    (link / "grant").symlink_to(real)
    assert window(real).open                               # the target alone would be open
    assert not window(str(link / "grant")).open


def test_symlinked_dir_is_closed(tmp_path):
    real = write_grant(tmp_path)
    (tmp_path / "dirlink").symlink_to(Path(real).parent)
    assert not window(str(tmp_path / "dirlink" / "grant")).open


def test_fifo_is_closed_without_hanging(tmp_path):
    d = tmp_path / "fifodir"
    d.mkdir()
    os.chmod(d, 0o755)
    os.mkfifo(d / "grant", 0o644)
    assert not window(str(d / "grant")).open


@pytest.mark.parametrize("raw", ["", "not json", "[]", "{}", "null", '{"expires_utc": 5}', "\xff\xfe"])
def test_junk_is_closed(tmp_path, raw):
    assert not window(write_grant(tmp_path, raw=raw)).open


def test_missing_file_and_dir_are_closed(tmp_path):
    (tmp_path / "d").mkdir()
    os.chmod(tmp_path / "d", 0o755)
    assert window(str(tmp_path / "d" / "grant")).reason == "no window is open"
    assert not window(str(tmp_path / "nodir" / "grant")).open


def test_oversize_file_is_closed(tmp_path):
    assert not window(write_grant(tmp_path, raw=" " * 5000 + json.dumps({"expires_utc": iso(NOW + 5)}))).open


@pytest.mark.parametrize("extra", [
    {"duration_s": True},                           # a bool is not a duration
    {"duration_s": 30},                             # below the helper's 60 s minimum (and not expires - granted)
    {"nonce": "xyz"},
    {"granted_by_uid": "501"},
    {"expires_utc": "2027-01-01T00:00:00+00:00"},
    {"granted_utc": "yesterday"},
])
def test_schema_violations_are_closed(tmp_path, extra):
    assert not window(write_grant(tmp_path, extra=extra)).open


def test_granted_in_the_future_is_closed(tmp_path):
    assert not window(write_grant(tmp_path, granted=NOW + 3600, duration=3600)).open


def test_expiry_not_matching_duration_is_closed(tmp_path):
    assert not window(write_grant(tmp_path, extra={"expires_utc": iso(NOW + 100)})).open


# ---------------------------------------------------------------- the policy


def rq(name="Bash", command=None, kind="tool", provider="claude", inp=None, detail=None, title="", description="",
       metadata=None):
    if inp is None and command is not None:
        inp = {"command": command, "description": "glossed by the agent"}
    if detail is None and command is not None and name in ("Bash", "CodexBash"):
        detail = {"type": "shell", "command": command}
    return W.Request(AGENT, "permission-1", provider, name, kind, title, description, inp, detail, metadata)


def verdict(req) -> W.Decision:
    return W.decide(req, HOME)


SCREENSHOT = "rm -f $S/all.done $S/*.log"


def test_the_screenshot_command_is_allowed():
    d = verdict(rq(command=SCREENSHOT, title="", description=""))
    assert d.allow and d.rule == "allow:window" and d.subject == SCREENSHOT


def test_the_screenshot_reason_text_is_allowed():
    reason = ('Dangerous rm operation on possibly-empty variable path: $S/*.log in `rm -f $S/all.done $S/*.log` '
              '(rewrite it as "${S:?}"/*.log or use a literal path)')
    assert verdict(rq(command=SCREENSHOT, description=reason)).allow


@pytest.mark.parametrize("command", [
    "git status", "rm -rf ./build", "rm -rf /tmp/xyz", f"rm -rf {HOME}/src/x-wt", 'rm -rf "$HOME/src/x-wt"', "rm -f /*.log",
    "rm -rf /usr/local/lib/old", "rm -rf /var/folders/ab/cd", "rm -rf /Users/tester/src/old", "rm file-with-system-in-name",
    'S=/tmp/x; rm -f $S/a $S/*.log', "diskutil list", "dscl . -read /Users/tester", "security find-identity -v",
    "chmod -R 755 ./dist", "find . -name '*.pyc' -delete", "echo passwd", "cat /etc/passwd", "ls /Volumes",
    "rm -rf /Volumes/Backup/old/2020", "python3 -c 'print(1)'", "sudo-secretspec-docs-are-not-here" if False else "ls docs",
])
def test_ordinary_commands_are_allowed(command):
    d = verdict(rq(command=command))
    assert d.allow, (command, d.rule)


@pytest.mark.parametrize("command", [
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf ~/", "rm -rf ~/*", 'rm -rf "$HOME"', "rm -rf ${HOME}/", f"rm -rf {HOME}",
    "rm -rf /Users", "rm -rf /Users/tester", "rm -rf /Users/someone-else", "rm -rf /System", "rm -rf /System/Library/x",
    "rm -rf /usr", "rm -rf /usr/bin", "rm -rf /etc", "rm -f /etc/hosts", "rm -rf /var", "rm -rf /private", "rm -rf /private/etc",
    "rm -rf /Volumes/Backup", "rm -rf /Volumes/Backup/", "rm -rf $S/", "rm -rf $S/*", 'rm -rf "${S}"/', "rm -rf /opt/homebrew",
    "rm -r /Applications", "rm -rf /bin /tmp/ok", "cd /tmp && rm -rf /", "sh -c 'rm -rf /usr'", "bash -c \"echo hi; rm -rf ~\"",
    "find / -delete", "find ~ -name x -delete", "chmod -R 777 /usr", "chown -R nobody /Users", "rmdir /Users", "sudo rm -rf /",
    "rm --recursive --force /", "ls | xargs rm -rf ~",
])
def test_critical_path_removal_stays_pending(command):
    d = verdict(rq(command=command))
    assert not d.allow and d.rule.startswith("critical-rm:"), (command, d.rule)


def test_a_critical_path_reason_stays_pending():
    d = verdict(rq(command="rm -rf build", description="Dangerous rm operation on critical path /Users"))
    assert not d.allow and d.rule == "critical-reason"


def test_a_symlink_cannot_hide_a_critical_path(tmp_path):
    link = tmp_path / "etc-link"
    link.symlink_to("/etc")
    d = verdict(rq(command=f"rm -rf {link}"))
    assert not d.allow and d.rule.startswith("critical-rm:")


DENYLIST = [
    "cat /etc/sudoers", "echo x >> /etc/sudoers.d/agent", "visudo", "/usr/sbin/visudo -f x", "vim /etc/pam.d/sudo",
    "sed -i '' s/a/b/ /private/etc/pam.d/sudo_local", "sudo-ask grant 8h", "sudo-ask --grant", "sudo-ask revoke",
    "/usr/local/libexec/sudo-ask-granted exec -- id", "cat /var/db/sudo-ask/grant", "rm /var/db/sudo-ask/grant",
    "echo x > /private/var/db/sudo-ask/grant", "sqlite3 '/Library/Application Support/com.apple.TCC/TCC.db' .dump",
    "cp ~/Library/Application\\ Support/com.apple.TCC/TCC.db /tmp", "tccutil reset All", "sudo-secretspec get SOME_KEY",
    "sudo-secretspec", "ls /opt/sudo-secretspec-test", "cat /usr/local/sbin/sudo-secretspec-broker", "ls /usr/local/libexec",
    "diskutil eraseDisk APFS X disk9", "diskutil secureErase 0 disk9", "diskutil apfs deleteVolume disk3s5", "diskutil",
    "sh -c 'diskutil eraseVolume HFS+ X disk9s1'", "csrutil disable", "csrutil status", "nvram boot-args=x", "nvram -p",
    "dscl . -append /Groups/admin GroupMembership evil", "dscl . -create /Users/x", "dscl . -delete /Users/x", "dscl",
    "dseditgroup -o edit -a x -t user admin", "security delete-keychain x.keychain", "security add-generic-password -s a",
    "security unlock-keychain", "security", "cp ~/Library/Keychains/login.keychain-db /tmp", "cat /Library/Keychains/System.keychain",
    "fdesetup disable", "passwd", "pwpolicy -u x", "newfs_apfs disk9", "mkfs.ext4 x", "sysadminctl -addUser x",
    "systemsetup -setremotelogin on", "ls /var/db/dslocal/nodes/Default/users",
]


@pytest.mark.parametrize("command", DENYLIST)
def test_denylist_commands_stay_pending(command):
    d = verdict(rq(command=command))
    assert not d.allow and d.rule.startswith("denylist:"), (command, d.rule)


@pytest.mark.parametrize("path", ["/etc/sudoers", "/etc/sudoers.d/agent", "/private/etc/pam.d/sudo", "/var/db/sudo-ask/grant",
                                  "/usr/local/libexec/sudo-ask-granted", "/Library/Keychains/System.keychain",
                                  "/Users/tester/Library/Application Support/com.apple.TCC/TCC.db"])
@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
def test_denylist_paths_in_file_tools_stay_pending(tool, path):
    d = verdict(rq(name=tool, inp={"file_path": path, "content": "x", "old_string": "a", "new_string": "b"}))
    assert not d.allow and d.rule.startswith("denylist:")


def test_prose_in_a_written_file_is_not_an_edit():
    d = verdict(rq(name="Write", inp={"file_path": "/Users/tester/src/doc.md", "content": "edit /etc/sudoers with visudo"}))
    assert d.allow
    d = verdict(rq(name="Edit", inp={"file_path": "/Users/tester/src/doc.md", "old_string": "sudoers", "new_string": "pam.d"}))
    assert d.allow


def test_the_denylist_beats_the_screenshot_class():
    assert not verdict(rq(command="rm -f $S/all.done $S/*.log /etc/sudoers.d/x")).allow


def test_codex_command_card_is_judged_by_its_command():
    ok = rq(name="CodexBash", provider="codex", title="Run command: rm -f $S/x.log",
            inp={"command": "rm -f $S/x.log", "cwd": "/tmp"}, detail={"type": "shell", "command": "rm -f $S/x.log"})
    assert verdict(ok).allow
    bad = rq(name="CodexBash", provider="codex", title="Run command: visudo", inp={"command": "visudo", "cwd": "/tmp"})
    assert not verdict(bad).allow


def test_codex_titles_alone_are_read_as_the_command():
    only_title = rq(name="CodexBash", provider="codex", title="Run command: rm -rf /", inp={"cwd": "/tmp"})
    assert verdict(only_title).rule.startswith("critical-rm:")


def test_acp_request_with_the_command_in_its_raw_input():
    req = rq(name="execute", provider="cursor", title="Terminal", inp=None, detail={"type": "unknown", "input": None},
             metadata={"rawRequest": {"toolCall": {"rawInput": {"command": ["rm", "-rf", "/Users"]}}}})
    d = verdict(req)
    assert not d.allow and d.rule.startswith("critical-rm:")
    ok = rq(name="execute", provider="cursor", title="Terminal", inp=None,
            metadata={"rawRequest": {"toolCall": {"rawInput": {"command": "ls"}}}})
    assert verdict(ok).allow


def test_argv_list_is_read():
    d = verdict(rq(name="shell", provider="x", inp={"argv": ["rm", "-rf", "/"]}))
    assert not d.allow and d.rule.startswith("critical-rm:")


@pytest.mark.parametrize("req, why", [
    (rq(command=None, inp={}), "unreadable:no-command"),                                    # a Bash card with no command
    (rq(name="Bash", command=None, inp={"description": "only a gloss"}), "unreadable:no-command"),
    (rq(name="CodexFileChange", provider="codex", title="Apply file changes", description="needs write access"), "unreadable:no-path"),
    (rq(name="Write", inp={"content": "x"}), "unreadable:no-path"),
    (rq(name="SomeTool", inp=None, detail=None), "unreadable:no-details"),
    (rq(command="x" * (W.MAX_TEXT_CHARS + 1)), "unreadable:too-large"),
])
def test_unreadable_requests_stay_pending(req, why):
    d = verdict(req)
    assert not d.allow and d.rule == why


@pytest.mark.parametrize("kind", ["plan", "question", "mode", "other", ""])
def test_non_tool_kinds_stay_pending(kind):
    d = verdict(rq(command="ls", kind=kind))
    assert not d.allow and d.rule.startswith("kind:")


@pytest.mark.parametrize("name", ["AskUserQuestion", "ExitPlanMode", "EnterPlanMode", "CodexPlanApproval", "request_user_input",
                                  "CodexMcpElicitation", "switch_mode", "question", ""])
def test_questions_and_plans_stay_pending_even_as_tools(name):
    d = verdict(rq(name=name, inp={"questions": [{"question": "ok?"}]}, kind="tool"))
    assert not d.allow


def test_mcp_tools_and_unusual_tools_are_allowed():
    assert verdict(rq(name="mcp__basic-memory__bm_write", inp={"project": "main", "title": "n", "content": "a /etc/sudoers note"})).allow
    assert verdict(rq(name="WebFetch", inp={"url": "https://example.com", "prompt": "summarize"})).allow
    assert verdict(rq(name="mcp__paseo__create_agent", inp={"title": "x", "initialPrompt": "go"})).allow


def test_subject_is_cut_and_redacted():
    cmd = "curl -H 'Authorization: Bearer abcdef' https://x.test/ " + "a" * 300
    d = verdict(rq(command=cmd))
    assert d.allow and len(d.subject) <= W.COMMAND_PREFIX_CHARS and "abcdef" not in d.subject
    d = verdict(rq(command="echo ghp_abcdefghijklmnopqrstuvwxyz0123456789"))
    assert "ghp_abc" not in d.subject


# ---------------------------------------------------------------- the responder against a fake daemon


class FakeDaemon:
    def __init__(self, pending, fail_list=False, fail_allow=None):
        self.pending, self.fail_list, self.fail_allow = pending, fail_list, fail_allow or set()
        self.calls = []

    def list_pending(self):
        self.calls.append(("list",))
        if self.fail_list:
            raise W.DaemonError("daemon unreachable: ConnectionRefusedError")
        return list(self.pending)

    def allow(self, agent_id, request_id):
        self.calls.append(("allow", agent_id, request_id))
        if request_id in self.fail_allow:
            raise W.DaemonError("allow not confirmed")


def pending(*specs):
    out = []
    for i, (name, command, kind) in enumerate(specs):
        out.append(W.Request(AGENT, "permission-%d" % i, "claude", name, kind, "", "",
                             {"command": command} if command is not None else {"questions": [{"question": "q?"}]}, None, None))
    return out


def lines(log_path: Path):
    return [json.loads(x) for x in log_path.read_text().splitlines()] if log_path.exists() else []


def test_window_closed_does_nothing(tmp_path):
    log = W.AuditLog(tmp_path / "log" / "permits.jsonl")
    daemon = FakeDaemon(pending(("Bash", SCREENSHOT, "tool")))
    res = W.sweep(daemon, log, grant_path=str(tmp_path / "none" / "grant"), now=lambda: NOW, owner_uid=UID, home=HOME)
    assert not res.window.open and (res.allowed, res.held, res.errors) == (0, 0, 0)
    assert daemon.calls == [] and not (tmp_path / "log").exists()


def test_expired_window_does_nothing(tmp_path):
    grant = write_grant(tmp_path, granted=NOW - 7200, duration=3600)
    daemon = FakeDaemon(pending(("Bash", SCREENSHOT, "tool")))
    W.sweep(daemon, W.AuditLog(tmp_path / "p.jsonl"), grant_path=grant, now=lambda: NOW, owner_uid=UID, home=HOME)
    assert daemon.calls == []


def test_open_window_allows_and_holds(tmp_path):
    grant = write_grant(tmp_path)
    log_path = tmp_path / "state" / "permits.jsonl"
    daemon = FakeDaemon(pending(("Bash", SCREENSHOT, "tool"), ("Bash", "rm -rf /Users", "tool"), ("AskUserQuestion", None, "question"),
                                ("Bash", "cat /etc/sudoers", "tool"), ("Bash", "git status", "tool")))
    res = W.sweep(daemon, W.AuditLog(log_path), grant_path=grant, now=lambda: NOW, owner_uid=UID, home=HOME)
    assert (res.allowed, res.held, res.errors) == (2, 3, 0)
    assert daemon.calls == [("list",), ("allow", AGENT, "permission-0"), ("allow", AGENT, "permission-4")]
    rows = lines(log_path)
    assert [(r["decision"], r["rule"]) for r in rows] == [
        ("allow", "allow:window"), ("hold", "critical-rm:rm /Users"), ("hold", "kind:question"),
        ("hold", "denylist:sudoers"), ("allow", "allow:window")]
    first = rows[0]
    assert first["agent"] == AGENT and first["provider"] == "claude" and first["tool"] == "Bash"
    assert first["command"] == SCREENSHOT and first["time"].endswith("Z") and len(first["command"]) <= 200
    assert oct(log_path.stat().st_mode & 0o777) == "0o600" and oct(log_path.parent.stat().st_mode & 0o777) == "0o700"


def test_a_log_that_cannot_be_written_allows_nothing(tmp_path):
    grant = write_grant(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the log directory should be")
    daemon = FakeDaemon(pending(("Bash", "git status", "tool")))
    with pytest.raises(OSError):
        W.sweep(daemon, W.AuditLog(blocker / "permits.jsonl"), grant_path=grant, now=lambda: NOW, owner_uid=UID, home=HOME)
    assert ("allow", AGENT, "permission-0") not in daemon.calls


def test_window_rechecked_before_each_allow(tmp_path):
    grant = write_grant(tmp_path, granted=NOW - 10, duration=100)     # expires at NOW + 90
    times = iter([NOW, NOW + 200, NOW + 200])                          # open at sweep start, expired before the first allow
    daemon = FakeDaemon(pending(("Bash", "git status", "tool")))
    res = W.sweep(daemon, W.AuditLog(tmp_path / "p.jsonl"), grant_path=grant, now=lambda: next(times), owner_uid=UID, home=HOME)
    assert res.allowed == 0 and daemon.calls == [("list",)]


def test_daemon_list_failure_is_logged_not_approved(tmp_path):
    grant = write_grant(tmp_path)
    log_path = tmp_path / "p.jsonl"
    res = W.sweep(FakeDaemon([], fail_list=True), W.AuditLog(log_path), grant_path=grant, now=lambda: NOW, owner_uid=UID, home=HOME)
    assert res.errors == 1 and lines(log_path)[0]["decision"] == "error" and lines(log_path)[0]["rule"].startswith("list:")


def test_allow_failure_is_an_error_line_and_the_sweep_continues(tmp_path):
    grant = write_grant(tmp_path)
    log_path = tmp_path / "p.jsonl"
    daemon = FakeDaemon(pending(("Bash", "git status", "tool"), ("Bash", "ls", "tool")), fail_allow={"permission-0"})
    res = W.sweep(daemon, W.AuditLog(log_path), grant_path=grant, now=lambda: NOW, owner_uid=UID, home=HOME)
    assert (res.allowed, res.errors) == (1, 1)
    assert [r["decision"] for r in lines(log_path)] == ["allow", "error", "allow"]


def test_held_requests_are_logged_once_per_watch(tmp_path):
    grant = write_grant(tmp_path)
    log_path = tmp_path / "p.jsonl"
    daemon = FakeDaemon(pending(("Bash", "visudo", "tool")))
    seen: set = set()
    for _ in range(3):
        W.sweep(daemon, W.AuditLog(log_path), grant_path=grant, now=lambda: NOW, owner_uid=UID, home=HOME, seen=seen)
    assert len(lines(log_path)) == 1


# ---------------------------------------------------------------- the wire (Paseo's Agent MCP route), no socket


def sse(msg) -> bytes:
    return ("event: message\ndata: " + json.dumps(msg) + "\n\n").encode()


def real_shape_payload():
    # the shape `list_pending_permissions` returned on 2026-11-22, ids replaced
    return {"permissions": [
        {"agentId": AGENT, "status": "running", "request": {
            "id": "permission-aaaaaaaa-0000-4000-8000-000000000001", "provider": "claude", "name": "AskUserQuestion",
            "kind": "question", "title": "Which?", "description": "A / B", "input": {"questions": [{"question": "Which?"}]},
            "metadata": {"toolUseId": "toolu_1"}}},
        {"agentId": AGENT, "status": "running", "request": {
            "id": "permission-aaaaaaaa-0000-4000-8000-000000000002", "provider": "claude", "name": "Bash", "kind": "tool",
            "input": {"command": SCREENSHOT, "description": "Remove temp files"},
            "detail": {"type": "shell", "command": SCREENSHOT}, "metadata": {"toolUseId": "toolu_2"}}},
    ]}


class FakeHttp:
    """An opener: records every call and answers like Paseo's /mcp/agents (SSE framing)."""

    def __init__(self, status=200, ctype="text/event-stream", respond=None):
        self.calls, self.status, self.ctype, self.respond = [], status, ctype, respond

    def __call__(self, url, body, headers, timeout):
        msg = json.loads(body)
        self.calls.append((url, msg, headers))
        name = msg["params"]["name"]
        if self.respond is not None:
            return self.status, self.ctype, self.respond(msg)
        if name == "list_pending_permissions":
            result = {"content": [], "structuredContent": real_shape_payload()}
        else:
            result = {"content": [], "structuredContent": {"success": True}}
        return self.status, self.ctype, sse({"jsonrpc": "2.0", "id": msg["id"], "result": result})


def test_wire_list_and_allow():
    http = FakeHttp()
    d = W.McpDaemon(opener=http)
    reqs = d.list_pending()
    assert [r.name for r in reqs] == ["AskUserQuestion", "Bash"] and reqs[1].detail["type"] == "shell"
    d.allow(AGENT, reqs[1].request_id)
    (url1, m1, h1), (url2, m2, _) = http.calls
    assert url1 == url2 == "http://127.0.0.1:7263/mcp/agents"
    assert m1["method"] == "tools/call" and m1["params"] == {"name": "list_pending_permissions", "arguments": {}}
    assert m2["params"] == {"name": "respond_to_permission", "arguments": {
        "agentId": AGENT, "requestId": reqs[1].request_id, "response": {"behavior": "allow"}}}
    assert "text/event-stream" in h1["Accept"] and h1["Content-Type"] == "application/json"


def test_wire_plain_json_answer():
    d = W.McpDaemon(opener=FakeHttp(ctype="application/json", respond=lambda m: json.dumps(
        {"jsonrpc": "2.0", "id": m["id"], "result": {"structuredContent": {"permissions": []}}}).encode()))
    assert d.list_pending() == []


@pytest.mark.parametrize("http", [
    FakeHttp(status=500),
    FakeHttp(status=401),
    FakeHttp(respond=lambda m: b"event: message\ndata: not json\n\n"),
    FakeHttp(respond=lambda m: sse({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32000, "message": "x"}})),
    FakeHttp(respond=lambda m: sse({"jsonrpc": "2.0", "id": m["id"], "result": {"isError": True, "content": []}})),
    FakeHttp(respond=lambda m: sse({"jsonrpc": "2.0", "id": m["id"], "result": {"content": []}})),
    FakeHttp(respond=lambda m: sse({"jsonrpc": "2.0", "id": 999, "result": {"structuredContent": {"permissions": []}}})),
    FakeHttp(respond=lambda m: sse({"jsonrpc": "2.0", "id": m["id"], "result": {"structuredContent": {"permissions": "x"}}})),
    FakeHttp(respond=lambda m: sse({"jsonrpc": "2.0", "id": m["id"], "result": {"structuredContent": {"permissions": [{"agentId": "a"}]}}})),
])
def test_wire_bad_answers_raise(http):
    with pytest.raises(W.DaemonError):
        W.McpDaemon(opener=http).list_pending()


def test_wire_connection_error_and_unconfirmed_allow():
    def boom(url, body, headers, timeout):
        raise ConnectionRefusedError("down")
    with pytest.raises(W.DaemonError):
        W.McpDaemon(opener=boom).list_pending()
    no = FakeHttp(respond=lambda m: sse({"jsonrpc": "2.0", "id": m["id"], "result": {"structuredContent": {"success": False}}}))
    with pytest.raises(W.DaemonError):
        W.McpDaemon(opener=no).allow(AGENT, "permission-1")


@pytest.mark.parametrize("url", ["https://127.0.0.1:7263/mcp/agents", "http://example.com/mcp/agents", "http://127.0.0.1:7263/mcp",
                                 "http://127.0.0.1:7263/mcp/agents?callerAgentId=x", "http://10.0.0.5:7263/mcp/agents"])
def test_only_the_loopback_agent_route_is_used(url):
    with pytest.raises(W.DaemonError):
        W.McpDaemon(url, opener=FakeHttp())


def test_wire_end_to_end_sweep(tmp_path):
    grant = write_grant(tmp_path)
    http = FakeHttp()
    log_path = tmp_path / "p.jsonl"
    res = W.sweep(W.McpDaemon(opener=http), W.AuditLog(log_path), grant_path=grant, now=lambda: NOW, owner_uid=UID, home=HOME)
    assert (res.allowed, res.held) == (1, 1)
    assert [c[1]["params"]["name"] for c in http.calls] == ["list_pending_permissions", "respond_to_permission"]
    assert http.calls[1][1]["params"]["arguments"]["requestId"].endswith("0002")


def test_wire_closed_window_makes_no_http_call(tmp_path):
    http = FakeHttp()
    W.sweep(W.McpDaemon(opener=http), W.AuditLog(tmp_path / "p.jsonl"), grant_path=str(tmp_path / "x" / "grant"),
            now=lambda: NOW, owner_uid=UID, home=HOME)
    assert http.calls == []


# ---------------------------------------------------------------- the CLI entry point


class Out:
    def __init__(self):
        self.text = ""

    def write(self, s):
        self.text += s


def run_main(argv, tmp_path, daemon=None, grant=None, **kw):
    out = Out()
    code = W.main(argv, daemon=daemon, grant_path=grant or str(tmp_path / "nogrant" / "grant"), owner_uid=UID,
                  log_path=tmp_path / "state" / "permits.jsonl", now=lambda: NOW, out=out, home=HOME, **kw)
    return code, out.text


def test_status_open_and_closed(tmp_path):
    code, text = run_main(["status"], tmp_path)
    assert code == 1 and "closed" in text
    code, text = run_main(["status", "--json"], tmp_path, grant=write_grant(tmp_path))
    assert code == 0 and json.loads(text)["open"] is True and json.loads(text)["remaining_s"] == 3590
    code, text = run_main(["status"], tmp_path, grant=write_grant(tmp_path))
    assert code == 0 and "OPEN" in text


def test_status_never_contacts_the_daemon(tmp_path):
    daemon = FakeDaemon(pending(("Bash", "ls", "tool")))
    run_main(["status"], tmp_path, daemon=daemon, grant=write_grant(tmp_path))
    assert daemon.calls == []


def test_respond_needs_once_and_known_options(tmp_path):
    assert run_main(["respond"], tmp_path)[0] == 64
    assert run_main(["respond", "--once", "--bogus"], tmp_path)[0] == 64
    assert run_main(["respond", "--once", "--interval", "1"], tmp_path)[0] == 64
    assert run_main(["frobnicate"], tmp_path)[0] == 64
    assert run_main([], tmp_path)[0] == 64


def test_respond_once_sweeps(tmp_path):
    daemon = FakeDaemon(pending(("Bash", SCREENSHOT, "tool"), ("Bash", "visudo", "tool")))
    code, text = run_main(["respond", "--once"], tmp_path, daemon=daemon, grant=write_grant(tmp_path))
    assert code == 0 and "allowed 1, held 1" in text
    assert daemon.calls == [("list",), ("allow", AGENT, "permission-0")]
    daemon = FakeDaemon([])
    run_main(["respond", "--once"], tmp_path, daemon=daemon)           # closed
    assert daemon.calls == []


def test_respond_reports_daemon_errors_in_the_exit_code(tmp_path):
    code, _ = run_main(["respond", "--once"], tmp_path, daemon=FakeDaemon([], fail_list=True), grant=write_grant(tmp_path))
    assert code == 1


def test_a_second_responder_does_not_run(tmp_path):
    held = W._lock(tmp_path / "state" / "permits.jsonl")
    try:
        daemon = FakeDaemon(pending(("Bash", "ls", "tool")))
        code, text = run_main(["respond", "--once"], tmp_path, daemon=daemon, grant=write_grant(tmp_path))
        assert code == 1 and "lock" in text and daemon.calls == []
    finally:
        held.close()


def make_clock():
    t = {"now": 0.0, "slept": []}

    def monotonic():
        return t["now"]

    def sleep(s):
        t["slept"].append(s)
        t["now"] += s
    return monotonic, sleep, t


def test_watch_never_polls_faster_than_two_seconds_and_skips_the_daemon_without_a_grant(tmp_path):
    mono, sleep, t = make_clock()
    daemon = FakeDaemon(pending(("Bash", "ls", "tool")))
    code, _ = run_main(["watch", "--interval", "0.1", "--duration", "10"], tmp_path, daemon=daemon, monotonic=mono, sleep=sleep)
    assert code == 0 and daemon.calls == [] and t["slept"] and min(t["slept"]) >= 2.0 and len(t["slept"]) == 5


def test_watch_sweeps_while_a_grant_exists(tmp_path):
    mono, sleep, t = make_clock()
    daemon = FakeDaemon(pending(("Bash", "git status", "tool")))
    run_main(["watch", "--interval", "5", "--duration", "10"], tmp_path, daemon=daemon, grant=write_grant(tmp_path),
             monotonic=mono, sleep=sleep)
    assert daemon.calls.count(("list",)) == 2 and t["slept"] == [5.0, 5.0]


def test_watch_with_an_expired_grant_file_does_not_contact_the_daemon(tmp_path):
    mono, sleep, _ = make_clock()
    daemon = FakeDaemon(pending(("Bash", "git status", "tool")))
    run_main(["watch", "--duration", "6"], tmp_path, daemon=daemon, grant=write_grant(tmp_path, granted=NOW - 9000),
             monotonic=mono, sleep=sleep)
    assert daemon.calls == []


# ---------------------------------------------------------------- the Claude PermissionRequest hook


def hook_payload(tool="Bash", tool_input=None, event="PermissionRequest"):
    return {"session_id": "s1", "hook_event_name": event, "tool_name": tool,
            "tool_input": {"command": SCREENSHOT} if tool_input is None else tool_input}


ALLOW = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}


def run_hook(payload, tmp_path, grant):
    return HOOK.decision_for(payload, grant_path=grant, owner_uid=UID, log_path=tmp_path / "hook" / "p.jsonl", home=HOME, now=NOW)


def test_hook_allows_in_an_open_window(tmp_path, monkeypatch):
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    assert run_hook(hook_payload(), tmp_path, write_grant(tmp_path)) == ALLOW
    row = lines(tmp_path / "hook" / "p.jsonl")[0]
    assert row["decision"] == "allow" and row["agent"] == "s1" and row["provider"] == "claude" and row["command"] == SCREENSHOT


def test_hook_has_no_opinion_when_closed(tmp_path):
    assert run_hook(hook_payload(), tmp_path, str(tmp_path / "x" / "grant")) is None
    assert run_hook(hook_payload(), tmp_path, write_grant(tmp_path, granted=NOW - 9000)) is None
    assert not (tmp_path / "hook").exists()


@pytest.mark.parametrize("payload", [
    hook_payload(tool_input={"command": "rm -rf /Users"}),
    hook_payload(tool_input={"command": "cat /etc/sudoers"}),
    hook_payload(tool_input={}),
    hook_payload(tool="AskUserQuestion", tool_input={"questions": [{"question": "q"}]}),
    hook_payload(tool="ExitPlanMode", tool_input={"plan": "do it"}),
    hook_payload(tool="Write", tool_input={"file_path": "/etc/sudoers.d/x", "content": "x"}),
    hook_payload(event="PreToolUse"),
    {"hook_event_name": "PermissionRequest"},
    {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": "a string"},
    "not a dict",
])
def test_hook_leaves_the_rest_to_the_prompt(tmp_path, payload):
    assert run_hook(payload, tmp_path, write_grant(tmp_path)) is None


def test_hook_with_an_unwritable_log_decides_nothing(tmp_path):
    blocker = tmp_path / "hook"
    blocker.write_text("file")
    with pytest.raises(OSError):                          # decision_for raises; main() turns any error into silence
        HOOK.decision_for(hook_payload(), grant_path=write_grant(tmp_path), owner_uid=UID, log_path=blocker / "p.jsonl", home=HOME, now=NOW)


@pytest.mark.parametrize("stdin", ["", "garbage", "[]", json.dumps({"hook_event_name": "PreToolUse"}), json.dumps(
    {"hook_event_name": "PermissionRequest", "tool_name": ""})])
def test_hook_process_prints_nothing_and_exits_zero(stdin):
    r = subprocess.run([sys.executable, str(REPO / "claude/hooks/approval_window_permit.py")], input=stdin,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and r.stdout == ""


def test_hook_main_prints_the_allow_object(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(HOOK, "decision_for", lambda payload: ALLOW)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("{}"))
    assert HOOK.main() == 0
    assert json.loads(capsys.readouterr().out) == ALLOW


def test_hook_main_survives_any_error(monkeypatch, capsys):
    def boom(payload):
        raise RuntimeError("x")
    monkeypatch.setattr(HOOK, "decision_for", boom)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("{}"))
    assert HOOK.main() == 0 and capsys.readouterr().out == ""


# ---------------------------------------------------------------- the checked-in pieces


def test_cli_wrapper_is_executable_and_status_runs():
    wrapper = REPO / "bin" / "ade-approval-window"
    assert os.access(wrapper, os.X_OK)
    r = subprocess.run([sys.executable, "-I", str(wrapper), "status", "--json"], capture_output=True, text=True, timeout=20)
    assert r.returncode in (0, 1) and set(json.loads(r.stdout)) == {"open", "reason", "expires_epoch", "remaining_s"}


def test_launchd_template_runs_a_bounded_watch_and_is_never_auto_loaded():
    text = (REPO / "config/launchd/com.djbclark.ade-approval-window.plist").read_text()
    assert "<string>watch</string>" in text and "--duration" in text and "<key>RunAtLoad</key><false/>" in text
    assert "Template only" in text and "KeepAlive" not in text
