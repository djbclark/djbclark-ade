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
    "diskutil list", "dscl . -read /Users/tester", "security find-identity -v",
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


# ---------------------------------------------------------------- adversary round 1 (PR 939): shells, gates, removal families


def held(command=None, **kw):
    return verdict(rq(command=command, **kw))


def argv_req(*argv):
    return rq(name="CodexBash", provider="codex", inp={"command": list(argv), "cwd": "/tmp"})


CODEX_CARDS = [
    "/bin/zsh -lc 'cd /tmp && rm -rf ~/'",
    "/bin/zsh -lc 'cd /tmp; rm -rf /System'",
    "/bin/zsh -lc 'rm -rf ~/'",
    'bash -c "cd /tmp; rm -rf $HOME/"',
    "bash -c 'a=1\nrm -rf /usr'",
    "bash -c 'true || rm -rf /etc'",
    "bash -c 'echo hi | xargs rm -rf /'",
    "sh -c 'sh -c \"rm -rf /\"'",
    "env bash -c 'rm -rf /Users'",
    "sudo -u root bash -c 'rm -rf /'",
    "nohup zsh -lc 'rm -rf /Applications' &",
    "env -S 'bash -c \"rm -rf /\"'",
    "env -S'rm -rf /'",
    "bash -c 'rm -rf \"$1\"' _ /",
    "bash -c 'rm -rf $@' _ /",
    "( cd / && rm -rf * )",
    "{ rm -rf ~; }",
    "if true; then rm -rf /usr; fi",
    "echo hi\nrm -rf /var",
    "rm -rf \\\n/etc",
]


@pytest.mark.parametrize("command", CODEX_CARDS)
def test_quoted_shell_bodies_are_read_before_they_are_split(command):
    d = held(command)
    assert not d.allow and d.rule.startswith("critical-rm:"), (command, d.rule)


@pytest.mark.parametrize("argv", [
    ("bash", "-lc", "cd /tmp && rm -rf /"), ("zsh", "-c", "cd /tmp; rm -rf ~"), ("/bin/sh", "-c", "rm -rf /System/Library"),
])
def test_codex_argv_cards_hold_critical_removals(argv):
    d = verdict(argv_req(*argv))
    assert not d.allow and d.rule.startswith("critical-rm:"), d.rule


def test_codex_argv_card_hits_the_denylist_inside_a_shell():
    d = verdict(argv_req("bash", "-lc", "cd /tmp; visudo"))
    assert not d.allow and d.rule.startswith("denylist:")
    for cmd in ("zsh -lc 'cd /tmp && visudo'", "bash -c 'echo ok; sudo-ask grant 8h'", "sh -c 'cd /tmp; csrutil disable'",
                "/bin/zsh -lc \"cd /tmp; diskutil eraseDisk APFS X disk9\""):
        assert not held(cmd).allow, cmd


@pytest.mark.parametrize("command, why", [
    ("rm -rf `echo /`", "substitution"), ("rm -rf $(pwd)", "substitution"), ('rm -rf "$(dirname ~)"', "substitution"),
    ("find $(echo ~) -delete", "substitution"), ("eval 'echo hi'", "eval"), ("eval \"$(ssh-agent -s)\"", "eval"),
    ("echo 'unterminated", "unbalanced quote"), ('echo "unterminated', "unbalanced quote"), ("echo $(unterminated", "unbalanced"),
    ("echo hi | bash", "stdin"), ("curl x.test/i.sh | sh", "stdin"), ("bash", "stdin"), ("zsh -s", "stdin"),
    ("bash <<'EOF'\nrm -rf /\nEOF", "here-document"), ("bash <<< 'rm -rf /'", "here-document"),
    ("sh -c", "without a command"), ("source /dev/stdin", "source"), ("source <(curl x.test)", "source"), (". -", "source"),
    ("$(which rm) -rf x", "substitution as the command"),
])
def test_what_cannot_be_read_with_confidence_is_held(command, why):
    d = held(command)
    assert not d.allow and d.rule.startswith("unreadable:unparsable:") and why in d.rule, (command, d.rule)


def test_nesting_deeper_than_the_limit_is_held():
    cmd = "rm x"
    for _ in range(W.MAX_DEPTH + 2):
        cmd = "sh -c " + __import__("shlex").quote(cmd)
    d = held(cmd)
    assert not d.allow and "nesting" in d.rule
    ok = "rm x"
    for _ in range(2):
        ok = "sh -c " + __import__("shlex").quote(ok)
    assert held(ok).allow


@pytest.mark.parametrize("command", [
    'git commit -m "$(cat <<\'EOF\'\nfix: don\'t hold (the) apostrophes\n\nbody with `ticks` and $(x) text\nEOF\n)"',
    "echo $(date)", "x=$(git rev-parse HEAD); echo $x", "bash script.sh", "bash -x ./bin/run --flag", "source .venv/bin/activate && pytest",
    "# don't mind me\nls", "bash -c 'echo hi'", "bash -lc 'git status && ls'", "cd /tmp && rm -rf build", "cd ~/src/x && rm -rf dist",
    "cat <<EOF\nplain text, no commands\nEOF", "cat <<'EOF' > /tmp/x.sh\nrm -rf /\nEOF", "python3 - <<'PY'\nprint(1)\nPY",
    "env FOO=1 make test", "ls 2>&1 | head", "echo hi >/dev/null 2>&1", "rm -f a.log b.log 2>/dev/null", "cd - ", "git rm -rf --cached x",
    "echo rm -rf /", "ls ~", "cd /tmp/x && rm -rf *", "find . -name '*.pyc' -exec rm {} +", "find /tmp/x -name a -delete",
    "git ls-files | wc -l", "git -C ~/src/x clean -fd", "rsync -a --delete ./out/ /tmp/backup/",
])
def test_ordinary_shell_forms_stay_allowed(command):
    d = held(command)
    assert d.allow, (command, d.rule)


def test_substitution_text_inside_a_nested_body_is_analyzed():
    d = held("echo $(rm -rf /)")
    assert not d.allow and d.rule.startswith("critical-rm:")
    d = held("cat <<EOF\n$(rm -rf /usr)\nEOF")
    assert not d.allow and d.rule.startswith("critical-rm:")
    assert held("cat <<'EOF'\n$(rm -rf /usr)\nEOF").allow            # quoted delimiter: the shell expands nothing


# MED 2: our own gates are never answered


@pytest.mark.parametrize("tool", ["Agent", "Task", "agent", "task"])
def test_subagent_launches_stay_pending(tool):
    d = verdict(rq(name=tool, inp={"subagent_type": "fable-deep", "prompt": "think hard", "description": "judge"}))
    assert not d.allow and d.rule == "gate:subagent"


def test_frontier_gate_shaped_request_stays_pending():
    reason = ("Frontier sub-agent: fable-deep runs on Fable, which is scarce (operator 2026-10-18). Approve only if this really "
              "needs it; ordinary judgment is Opus at high first")
    for name in ("Agent", "Bash", "mcp__x__y"):
        d = verdict(rq(name=name, inp={"subagent_type": "fable-deep", "command": "ls"}, description=reason, title="Frontier gate"))
        assert not d.allow and d.rule in ("gate:subagent", "gate:ade")
    d = verdict(rq(name="Bash", command="ls", metadata={"permissionDecisionReason": reason}))
    assert not d.allow and d.rule == "gate:ade"
    assert verdict(rq(name="mcp__paseo__create_agent", inp={"title": "x", "initialPrompt": "go"})).allow   # not Claude's launch tool


def test_the_marker_is_the_text_the_frontier_gate_really_asks_with():
    gate = (REPO / "claude/hooks/frontier_agent_gate.py").read_text()
    assert all(marker in gate for marker in W.GATE_MARKERS)


def test_hook_leaves_subagent_launches_to_the_prompt(tmp_path):
    p = hook_payload(tool="Agent", tool_input={"subagent_type": "fable-deep", "prompt": "x", "description": "d"})
    assert run_hook(p, tmp_path, write_grant(tmp_path)) is None
    assert lines(tmp_path / "hook" / "p.jsonl")[0]["rule"] == "gate:subagent"
    assert run_hook(hook_payload(tool="Task", tool_input={"subagent_type": "general-purpose", "prompt": "x"}), tmp_path,
                    write_grant(tmp_path)) is None


# MED 3: the removal family


@pytest.mark.parametrize("command", [
    "grm -rf ~", "gfind ~ -delete", "/bin/../bin/rm -rf ~", "/usr/bin/../bin/rm -rf /", "./rm -rf /usr", "grmdir /Users", "gunlink /etc/hosts",
    "find ~ -mindepth 1 -exec rm -rf {} +", "find ~ -exec rm {} \\;", "find / -execdir rm -rf {} +", "find -f / -delete", "find -H / -delete",
    "find -L ~ -ok rm {} \\;", "find ~ -exec sh -c 'rm -rf \"$1\"' _ {} \\;",
    "echo ~ | xargs rm -rf", "echo / | xargs rm -rf", "printf '%s\\n' ~ | xargs -n1 rm -rf", "find ~ -maxdepth 1 | xargs rm -rf",
    "echo /etc | xargs -0 rm", "cd ~ && rm -rf *", "cd / && rm -rf ./*", "cd $HOME && rm -rf .*", "cd ~ && rm -rf .", "cd /usr/local && rm -rf *",
    "cd /Users && rm -rf tester", "cd ~/.. && rm -rf *", "cd /etc && rm -f *", "cd ~ && find . -delete", "cd ~ && find -delete",
    "cd /Volumes/Backup && rm -rf *", "cd ~ && gfind . -exec rm {} +", "pushd ~ && rm -rf *",
    "rsync -a --delete /tmp/empty/ ~/", "rsync -a --delete-after /tmp/empty/ /", "git -C ~ clean -fdx", "cd ~ && git clean -fdx",
    "cd / && git clean -ffdx", "git clean -fdx ~", "rm --no-preserve-root -rf x", "cd ~ && chmod -R 000 *", "chmod -R 000 ~", "cd /usr && chown -R nobody .",
])
def test_the_whole_removal_family_is_judged(command):
    d = held(command)
    assert not d.allow and d.rule.startswith(("critical-rm:", "unreadable:unparsable:")), (command, d.rule)


def test_the_request_cwd_judges_relative_operands():
    req = rq(name="CodexBash", provider="codex", command=None, inp={"command": "rm -rf *", "cwd": HOME})
    assert verdict(req).rule.startswith("critical-rm:")
    ok = rq(name="CodexBash", provider="codex", command=None, inp={"command": "rm -rf *", "cwd": HOME + "/src/x"})
    assert verdict(ok).allow
    assert verdict(rq(name="CodexBash", provider="codex", command=None, inp={"command": "rm -rf build", "cwd": HOME})).allow


def test_cd_tracking_is_per_command_line_order():
    assert held("cd ~ && cd src && rm -rf *").allow        # a later cd moves away from the critical directory
    assert held("cd /tmp/x && rm -rf *").allow
    assert not held("cd src; cd ~; rm -rf *").allow
    assert not held("(cd ~ ; rm -rf *)").allow
    assert not held("rm -rf *; cd ~").allow                # round 3: no directory is known before the cd, so `*` is held
    assert not held("cd $UNKNOWN && rm -rf *").allow       # round 3: a cd to a variable, then a removal


def test_xargs_removal_of_unknown_input_is_held():
    d = held("ls /tmp/x | xargs rm -f")
    assert not d.allow and d.rule.startswith("unreadable:unparsable:xargs")
    assert held("echo /tmp/x | xargs rm -f").allow
    assert held("find /tmp/x -name '*.o' | xargs rm -f").allow


# LOW 4: tripwires also see quoting and path forms


@pytest.mark.parametrize("command", [
    "sudo tee /etc/sud''oers.d/x", 'sudo tee "/etc/sudo"ers', "sudo tee /var/db//sudo-ask/grant", "cat /var/db/./sudo-ask/grant",
    "cat /var/db/x/../sudo-ask/grant", "echo x > /var/db//sudo-ask/grant", "echo x > /etc/sud'o'ers",
])
def test_tripwires_see_through_quoting_and_path_forms(command):
    d = held(command)
    assert not d.allow and d.rule.startswith("denylist:"), (command, d.rule)


def test_double_slash_paths_in_file_tools_are_held():
    d = verdict(rq(name="Edit", inp={"file_path": "/var/db//sudo-ask/grant", "old_string": "a", "new_string": "b"}))
    assert not d.allow and d.rule.startswith("denylist:")


# site head f6dd14ba: persistence paths and programs


@pytest.mark.parametrize("command", [
    "cp x.plist /Library/LaunchDaemons/x.plist", "echo x > /Library/LaunchAgents/x.plist", "mv x /private/etc/periodic/daily/y",
    "tee /private/etc/zshrc", "cp x /private/etc/paths.d/y", "echo x >> /private/etc/profile", "cp k /private/var/root/.ssh/authorized_keys",
    "cp x /Library/StartupItems/y", "dd if=x of=/dev/disk3", "cp x /Users/tester/Library/Keychains/login.keychain-db",
    "crontab -e", "crontab /tmp/jobs", "launchctl load /tmp/x.plist", "launchctl submit -l x -- sh", "launchctl bootstrap system /x",
    "launchctl kickstart -k system/x", "launchctl enable system/x", "launchctl asuser 501 id", "date 0101000070", "sntp -sS x", "ntpdate x",
    "su -", "login", "at now", "batch", "chroot /x sh", "cp x /usr/lib/cron/tabs/y", "cd /Library/LaunchDaemons && cp x .",
    "sudo rm -rf /private/etc/ssh/ssh_config", "cp x /library/launchdaemons/y",
])
def test_site_persistence_denylist_is_mirrored(command):
    d = held(command)
    assert not d.allow and d.rule.startswith("denylist:"), (command, d.rule)


@pytest.mark.parametrize("command", [
    "cat /Library/LaunchDaemons/com.x.plist", "ls /Library/LaunchAgents", "grep x /private/etc/zshrc", "cp x ~/Library/LaunchAgents/y.plist",
    "crontab -l", "launchctl list", "launchctl print gui/501", "date +%s", "date -u +%FT%TZ", "echo at home", "echo su login", "cat /etc/paths",
    "launchctl bootout gui/501/x",
])
def test_user_level_and_read_only_forms_stay_allowed(command):
    d = held(command)
    assert d.allow, (command, d.rule)


@pytest.mark.parametrize("path", ["/Library/LaunchDaemons/x.plist", "/private/etc/zshrc", "/private/etc/paths.d/x", "/private/var/root/.zshrc"])
def test_file_tools_on_persistence_paths_are_held(path):
    for tool in ("Write", "Edit"):
        d = verdict(rq(name=tool, inp={"file_path": path, "content": "x", "old_string": "a", "new_string": "b"}))
        assert not d.allow and d.rule.startswith("denylist:"), (tool, path, d.rule)
    assert verdict(rq(name="Read", inp={"file_path": path})).allow            # reading is not a change


def test_user_launch_agents_are_not_protected():
    assert verdict(rq(name="Write", inp={"file_path": HOME + "/Library/LaunchAgents/com.x.plist", "content": "x"})).allow


# pinned to the site branch at f6dd14ba (read only; skipped where that checkout is absent)

SITE_WT = "/Users/djbclark/src/site-public-sudo-ask-grant-wt"
SITE_HEAD = "f6dd14ba778bb76bbbb0df226659de9754e4993e"
SITE_FILE = "roles/sudo_ask_grant/files/sudo-ask-granted"


def site_constants():
    import ast
    r = subprocess.run(["git", "-C", SITE_WT, "show", "%s:%s" % (SITE_HEAD, SITE_FILE)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        pytest.skip("site-public sudo-ask-grant worktree or head not present")
    wanted = {"PROTECTED", "PROTECTED_RE", "ALWAYS_DENY", "ALWAYS_DENY_PREFIX", "DISKUTIL_OK", "DISKUTIL_SUB_OK", "DSCL_WRITE",
              "DSCL_READ", "SECURITY_OK", "READ_ONLY", "TRIPWIRE", "MIN_SECONDS", "MAX_SECONDS", "CLOCK_SLACK"}
    out = {}
    for node in ast.parse(r.stdout).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", "") in wanted:
            out[node.targets[0].id] = eval(compile(ast.Expression(node.value), "site", "eval"), {"__builtins__": {}, "frozenset": frozenset, "set": set})
    return out


def test_policy_mirrors_the_site_denylist_at_the_pinned_head():
    site = site_constants()
    assert set(site["PROTECTED"]) == set(W.PROTECTED)
    assert tuple(site["PROTECTED_RE"]) == tuple(W.PROTECTED_RE)
    assert set(site["DISKUTIL_OK"]) == W.DISKUTIL_OK and set(site["DISKUTIL_SUB_OK"]) == W.DISKUTIL_SUB_OK
    assert set(site["DSCL_WRITE"]) == W.DSCL_WRITE and set(site["DSCL_READ"]) == W.DSCL_READ and set(site["SECURITY_OK"]) == W.SECURITY_OK
    assert set(site["READ_ONLY"]) == W.READ_ONLY
    assert (site["MIN_SECONDS"], site["MAX_SECONDS"], site["CLOCK_SLACK"]) == (W.MIN_WINDOW_S, W.MAX_WINDOW_S, W.CLOCK_SLACK_S)
    # programs the site denies under sudo: mirrored, except the ones that are ordinary user-level work for an agent
    user_level = {"ssh", "tmux", "screen", "script", "expect", "parallel", "watch", "entr", "osascript", "sudo-ask"}
    for name in set(site["ALWAYS_DENY"]) - user_level:
        assert name in W.NAME_DENY or name in W.TRIPWIRES or name.startswith("sudo-secretspec"), name
    assert set(site["ALWAYS_DENY_PREFIX"]) - {"sudo-secretspec"} <= set(W.NAME_DENY_PREFIX)
    for t in site["TRIPWIRE"]:
        assert any(t in mine or mine in t for mine in W.TRIPWIRES), t


# LOW 5, 6: the file swap and the hook's audit ids


def test_a_grant_swapped_between_lstat_and_open_is_closed(tmp_path, monkeypatch):
    grant = write_grant(tmp_path)
    real_open = os.open

    def swapping_open(path, flags, *a, **k):
        if str(path) == grant:
            replacement = Path(grant + ".new")
            replacement.write_text(Path(grant).read_text())
            os.chmod(replacement, 0o644)
            os.replace(replacement, grant)               # a different inode, same name, same bytes
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(W.os, "open", swapping_open)
    w = window(grant)
    assert not w.open and "changed" in w.reason


def test_hook_audit_lines_carry_a_session_and_input_hash(tmp_path, monkeypatch):
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    grant = write_grant(tmp_path)
    run_hook(hook_payload(tool_input={"command": "git status"}), tmp_path, grant)
    run_hook(hook_payload(tool_input={"command": "git diff"}), tmp_path, grant)
    run_hook(hook_payload(tool_input={"command": "git status"}), tmp_path, grant)
    rows = lines(tmp_path / "hook" / "p.jsonl")
    ids = [r["request"] for r in rows]
    assert all(i.startswith("s1:sha256-") and len(i) == len("s1:sha256-") + 12 for i in ids)
    assert ids[0] == ids[2] != ids[1]


def test_hook_uses_the_payload_cwd_for_relative_operands(tmp_path):
    p = hook_payload(tool_input={"command": "rm -rf *"})
    p["cwd"] = HOME
    assert run_hook(p, tmp_path, write_grant(tmp_path)) is None
    p["cwd"] = HOME + "/src/x"
    assert run_hook(p, tmp_path, write_grant(tmp_path)) == ALLOW


# ---------------------------------------------------------------- adversary round 2 (PR 939), fixed in round 3
# Stance (lead and operator, 2026-11-22): our agents are trusted, so these rules guard against CARELESS commands, not a hostile
# agent. Fail closed where the parser cannot be sure; do not out-parse the shell; a textual tripwire catches the runner forms.


def is_held(command, rule_prefix=("critical-rm:", "unreadable:unparsable:")):
    d = held(command)
    return (not d.allow) and d.rule.startswith(rule_prefix)


def cwd_req(command, cwd):
    return rq(name="CodexBash", provider="codex", command=None, inp={"command": command, "cwd": cwd})


# item 1 (HIGH): a variable the command line sets is UNKNOWN, not empty

VARIABLE_HOLDS = [
    "rm -f $S/a $S/*.log; S=/tmp/x", "S=; rm -rf $S/", "S=/ ; rm -rf ${S}", "rm -rf $S/; S=/tmp", "S=/ rm -rf $S",
    "export S=/; rm -rf $S", "declare S=/; rm -rf $S", "local S=/; rm -rf $S", "readonly S=/; rm -rf $S", "S+=/; rm -rf $S",
    "for d in /tmp/a /; do rm -rf $d; done", "for d in *; do rm -rf \"$d\"; done", "while read f; do rm -rf \"$f\"; done",
    "read X; rm -rf \"$X\"", "printf -v D /; rm -rf $D", "mapfile -t L; rm -rf ${L[0]}", "select d in /x /; do rm -rf $d; done",
    "f() { rm -rf \"$1\"; }; f /", "f() { rm -rf $@; }; f /Users", "function f { rm -rf \"$*\"; }; f ~", "rm -rf $1", "rm -rf ${1}", "rm -rf $0",
    "rm -rf ${S:-/}", "rm -rf ${S:=/}", "rm -rf ${S-/}", "rm -rf ${S/x/y}", "rm -rf ${!S}", "rm -rf ${#S}", "rm -rf $PWD/*", "rm -rf $OLDPWD",
    "HOME=/ ; rm -rf $HOME", "bash -c 'D=/; rm -rf $D'", "sh -c 'for d in /; do rm -rf $d; done'",
    "D=/; find $D -delete", "D=/; echo $D | xargs rm -rf", "D=/; git -C $D clean -fdx", "D=/; rsync -a --delete /tmp/e/ $D",
    "D=/; chmod -R 000 $D", "A=/; cd /tmp && rm -rf $A", "env S=/ sh -c 'rm -rf $S'", "F=-rf; rm $F /tmp/x",
]


@pytest.mark.parametrize("command", VARIABLE_HOLDS)
def test_a_variable_the_line_sets_is_unknown_not_empty(command):
    d = held(command)
    assert not d.allow and d.rule.startswith(("critical-rm:", "unreadable:unparsable:")), (command, d.rule)


def test_variable_holds_say_why():
    assert held("rm -f $S/a; S=/tmp/x").rule == "unreadable:unparsable:variable $S in a removal"
    assert "positional" not in held("rm -rf $1").rule and "$1" in held("rm -rf $1").rule
    assert "${S:-/}" in held("rm -rf ${S:-/}").rule


@pytest.mark.parametrize("command", [
    SCREENSHOT, "rm -rf $UNSET/x", "rm -f $S/all.done $S/*.log", "rm -f /tmp/foo.$$", "rm -rf $HOME/src/x-wt",
    "rm -rf ${HOME}/src/x", "S=/tmp/x; ls $S", "S=/tmp/x; echo $S; rm -rf ./build", "for f in a b; do echo $f; done",
    "rm -rf ./a$UNSET", "X=1 make test", "x=$(git rev-parse HEAD); echo $x",
])
def test_names_the_line_never_sets_stay_empty_and_other_uses_are_fine(command):
    d = held(command)
    assert d.allow, (command, d.rule)


# item 2 (MED): a glob or brace at the top of a critical directory

@pytest.mark.parametrize("command", [
    "rm -rf ~/{*,.*}", "rm -rf ~/?*", "rm -rf ~/[a-z]*", "rm -rf /Users/tester/{.,}*", "rm -rf ~/*.*", "rm -rf /Users/*", "rm -rf /usr/lo*",
    "rm -rf ~/Lib*", "rm -rf /Us*rs", "rm -rf /*", "rm -rf ~/.*", "rm -rf ~/**", "rm -rf ~/{a,b}", "rm -rf /Users/*/Library", "rm -rf /Volumes/*",
    "rm -rf /usr/bin/*.sh", "rm -rf /etc/*.conf", "rm -rf /tmp/*", "rm -rf $HOME/{*,.*}", "rm -rf ${HOME}/?*",
    "find ~/* -delete", "chmod -R 000 ~/[a-z]*", "cd ~ && rm -rf {*,.*}", "cd / && rm -rf ?*", "cd /Users/tester && rm -rf [a-z]*",
])
def test_a_glob_or_brace_at_the_top_of_a_critical_directory_is_held(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "rm -f /*.log", "rm -f /tmp/*.log", "rm -rf ~/src/*", "rm -rf /tmp/x/{a,b}", "rm -f $S/*.log", "rm -rf ~/src/x-wt/*",
    "rm -rf /var/folders/*/x", "rm -rf /Volumes/Backup/old/*",
])
def test_narrow_globs_and_globs_below_the_top_stay_allowed(command):
    assert held(command).allow, (command, held(command).rule)


# item 3 (MED): the working directory is unknown for a Paseo Claude request

@pytest.mark.parametrize("command", [
    "rm -rf .", "rm -rf ..", "rm -rf *", "rm -rf .*", "rm -rf ../x", "rm -rf ../../y", "rm -rf ./*", "rm -rf *.*", "rm -rf ?*", "rm -rf [a-z]*",
    "rm -rf {a,b}*", "rm -rf ./..", "find . -delete", "find -delete", "find .. -name x -delete", "find * -type f -delete", "chmod -R 000 .",
    "chmod -R 700 ../x", "git clean -fdx .", "git clean -fdx ..", "rsync -a --delete /tmp/e/ ..", "echo . | xargs rm -rf", "echo .. | xargs rm -rf",
    "find . | xargs rm -rf", "cd \"$(echo ~)\" && rm -rf build", "cd $X && rm -rf build", "cd $(pwd)/.. && rm -f x", "cd - && rm x", "cd `pwd` && rm -rf x",
    "cd $UNSET; rm -f ./a", "pushd \"$D\" && rm x", "popd && rm x", "cd \"\" && rm -rf *", "cd ~ && cd \"$1\" && rm -rf build",
    "git -C \"$(echo ~)\" clean -fdx", "git -C $D clean -fd", "git -C \"$X\" clean -fdx", "git -C .. clean -fdx", "cd $X && git clean -fdx",
    "echo $(echo ~) | xargs rm -rf", "printf '%s\\n' \"$(echo ~)\" | xargs rm -rf", "find $(echo ~) | xargs rm -rf", "echo `echo ~` | xargs rm",
])
def test_relative_removals_with_an_unknown_directory_are_held(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "rm -rf ./build", "rm -rf build", "rm -f *.log", "rm -f ./*.pyc", "find . -name '*.pyc' -delete", "find . -type f -name x -exec rm {} +", "rm -rf build/*",
    "git clean -fdx", "cd /tmp/x && rm -rf *", "git -C ~/src/x clean -fd", "rm -rf a/../b", "git --work-tree=/tmp/x clean -fd",
    "cd ~/src && cd x && rm -rf *", "cd $HOME/src/x && rm -rf *", "cd src && rm -rf ./out", "chmod -R 755 ./dist", "rm -rf /tmp/a $UNSET",
    "cd $X && ls", "cd $X && rm -rf /tmp/x",
])
def test_relative_removals_that_cannot_reach_the_whole_directory_stay_allowed(command):
    assert held(command).allow, (command, held(command).rule)


def test_a_known_request_directory_still_judges_relative_removals():
    assert not verdict(cwd_req("rm -rf .", HOME)).allow
    assert verdict(cwd_req("rm -rf .", HOME + "/src/x")).allow
    assert verdict(cwd_req("rm -rf *", HOME + "/src/x")).allow
    assert verdict(cwd_req("find . -delete", HOME + "/src/x")).allow
    assert not verdict(cwd_req("find . -delete", HOME)).allow
    assert not verdict(cwd_req("rm -rf ..", HOME + "/src")).allow
    assert not verdict(cwd_req("cd $X && rm -rf build", HOME + "/src/x")).allow     # a cd to a variable beats the known directory


# item 4 (MED): command words and runner forms; the textual tripwire

@pytest.mark.parametrize("command", [
    "parallel rm ::: x", "ssh host rm -rf x", "ssh host 'rm -rf /'", "fd -X rm", "fd . -x rm {}", "flock /tmp/l rm -rf x", "script -q /dev/null rm -rf x",
    "echo ~ | xargs -d '\\n' -n1 sh -c 'rm -rf $0'", "xargs -J % rm %", "echo a | xargs -I{} sh -c 'rm {}'", "find /tmp/x -exec sh -c 'rm -rf /' _ {} \\;",
    "find /tmp/x -name a -exec env rm {} \\;", "alias ls='rm -rf'", "alias x=rm", "f() { :; }; rm x", "function g { :; }; rm x", "x=1; y() { :; }\nrm -f z",
    "docker rm x", "aws s3 sync . s3://b --delete", "trash x", "tmux send-keys 'rm -rf /' Enter",
    "xargs -P4 -n1 -- rm", "time -p parallel rm", "nohup parallel rm", "echo x | parallel rm", "sudo --preserve-env parallel rm x",
    "env -i parallel rm", "cat list | while read f; do trash $f; done", "ruby -e 'system(\"rm x\")'",
])
def test_a_remover_word_the_parser_did_not_judge_holds_the_request(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "$'\\x72m' -rf /", "\"rm\" -rf x", "r\\m x", "r''m x", "/bin/r[m] x", "/bin/r? -rf x", "{rm,-rf,x}", "=rm x", "$RM -rf x", "\"$HOME/bin/tool\" a",
    "sudo $SUDO_CMD", "'git' status", "\\git status", "env $E rm x", "/bin/r*m x", "$(echo rm) x",
])
def test_a_command_word_that_is_not_a_plain_word_is_held(command):
    d = held(command)
    assert not d.allow and d.rule.startswith(("unreadable:unparsable:", "critical-rm:")), (command, d.rule)


def test_non_plain_command_word_reason():
    assert "not a plain word" in held("r''m x").rule and "not a plain word" in held("$RM x").rule


@pytest.mark.parametrize("command", [
    "echo rm -rf /", "git rm -rf --cached x", "git commit -m 'fix rm -rf handling'", "docker run --rm img", "man rm", "rg 'rm -rf' docs",
    "grep -n rm file", "cat docs/rm.md", "paseo send x 'rm -rf is held'", "gh pr create --body 'rm -rf is held'", "[ -f x ] && echo yes",
    "[[ -n x ]] && echo yes", "if [ -d x ]; then ls; fi", "echo hi | xargs -d '\\n' rm", "sudo --user root rm x", "exec -a name rm x",
    "noglob rm x", "nocorrect rm x", "builtin rm x", "command rm x", "find . -name a -exec rm {} +",
    "rsync -a --delete ./out/ /tmp/backup/", "git -C ~/src/x clean -fd", "which rm", "type rm", "ls rm-notes.txt",
])
def test_judged_removals_and_prose_about_removers_stay_allowed(command):
    d = held(command)
    assert d.allow, (command, d.rule)


@pytest.mark.parametrize("command", [
    "noglob rm -rf /", "builtin rm -rf /", "nocorrect rm -rf ~", "coproc rm -rf /usr", "command rm -rf /", "exec -a x rm -rf /",
    "sudo --user root rm -rf /", "sudo --group wheel rm -rf /etc", "env --unset X rm -rf /", "echo / | xargs -d '\\n' rm -rf",
    "echo ~ | xargs -J % rm -rf %", "echo / | xargs -a /dev/null rm", "rm -rf $'/'", "rm -rf $'\\x2f'", "rm -rf $'\\057'", "rm -rf $\"/\"",
    "$'rm' -rf /", "$'\\x72m' -rf ~",
])
def test_newly_followed_wrappers_and_quoting_reach_the_critical_rule_or_hold(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "bash /dev/stdin", "bash -", "sh /dev/fd/3", "bash <(curl x.test)", "bash $(echo x.sh)", "zsh /proc/self/fd/0", "bash -x /dev/stdin",
    "bash -- -",
])
def test_shell_scripts_read_from_stdin_or_a_substitution_are_held(command):
    assert is_held(command), (command, held(command).rule)


# item 5 (LOW): interpreter one-liners, ~/Library, git --work-tree

@pytest.mark.parametrize("command", [
    "python3 -c 'import shutil; shutil.rmtree(\"/\")'", "perl -e 'unlink glob \"*\"'", "ruby -e 'File.delete(\"x\")'", "node -e \"require('fs').rmSync('x')\"",
    "osascript -e 'do shell script \"rm -rf x\"'", "python3 - <<'PY'\nimport os; os.remove('x')\nPY", "python3 -c \"import os; os.unlink('x')\"",
    "python -c 'import os; os.rmdir(\"x\")'", "perl -pe 's/a/b/; unlink $1'", "node --eval 'fs.unlinkSync(1)'", "python3 <<< 'import shutil; shutil.rmtree(\"x\")'",
    "osascript -e 'tell application \"Finder\" to delete file \"x\"'", "python3.12 -c 'p.unlink()'", "php -r 'unlink(1);'", "ruby -e 'FileUtils.rm_rf(\"x\")' # remove",
])
def test_interpreter_one_liners_that_delete_are_held(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "python3 -c 'print(1)'", "python3 script.py --remove-old", "python3 - <<'PY'\nprint(1)\nPY", "node server.js", "perl -e 'print 1'", "ruby -e 'puts 1'",
    "osascript -e 'tell application \"Finder\" to activate'", "python3 -m pytest -k remove", "python3 -m pip install --editable .",
])
def test_ordinary_interpreter_calls_stay_allowed(command):
    assert held(command).allow, (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "rm -rf ~/Library", "rm -rf /Users/tester/Library", "rm -rf ~/Library/", "rm -rf ~/Library/*", "rm -rf ~/Library/Application\\ Support",
    "rm -rf '/Users/tester/Library/Application Support'", "rm -rf /Users/someone/Library",
    "cd ~ && rm -rf Library", "rm -rf $HOME/Library", "rmdir ~/Library", "find ~/Library -delete",
])
def test_removing_the_library_folder_itself_is_held(command):
    assert is_held(command, ("critical-rm:", "denylist:", "unreadable:")), (command, held(command).rule)


@pytest.mark.parametrize("command", ["rm -rf ~/Library/Caches/x", "rm -rf ~/Library/Logs/old.log", "rm -f ~/Library/Preferences/x.plist"])
def test_things_below_the_library_folder_stay_allowed(command):
    assert held(command).allow, (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "git --work-tree=/Users/tester clean -fdx", "git --work-tree ~ clean -fd", "git --work-tree=/ clean -fd", "git --work-tree=$X clean -fd",
    "git --work-tree=~/ -C /tmp clean -fdx", "git -C /tmp --work-tree=/usr/local clean -ffd", "git --git-dir=/tmp/x/.git --work-tree=/Users clean -fdx",
    "git --work-tree=.. clean -fdx",
])
def test_git_clean_follows_the_work_tree(command):
    assert is_held(command), (command, held(command).rule)


# LOW 4 stays documented: what the denylist does not see

def test_the_denylist_does_not_see_through_variables_and_globs():
    # documented in docs/approval-window.md (a note, not a boundary): a tripwire string assembled by the shell is not read
    assert held("cat /etc/sudo*").allow
    assert held("a=sudo; b=ers; cat /etc/$a$b").allow


def test_ansi_c_decoder():
    assert W._ansi_c("\\x72m") == "rm" and W._ansi_c("\\057") == "/" and W._ansi_c("a\\nb") == "a\nb" and W._ansi_c("\\u0041") == "A"
    assert W._ansi_c("\\q") == "\\q" and W._ansi_c("x\\") == "x\\"


@pytest.mark.parametrize("command", ["A=rm", "A='rm -rf /tmp/x'", "F=rm; echo done", "export R=rm"])
def test_an_assignment_that_stores_a_remover_word_is_held(command):
    assert is_held(command), (command, held(command).rule)


def test_the_library_folder_is_judged_for_any_home():
    d = W.decide(rq(command="rm -rf ~/Library"), "/srv/tester")
    assert not d.allow and d.rule.startswith("critical-rm:")
    assert W.decide(rq(command="rm -rf ~/Library/Caches/x"), "/srv/tester").allow


# ---------------------------------------------------------------- adversary round 3 (PR 939), fixed in round 4


def allowed_in(command, cwd=HOME + "/src/x"):
    return verdict(cwd_req(command, cwd)).allow


# item 1 (MED-1): a cd changes the judged directory only when `&&` (or `|| exit`) follows it

@pytest.mark.parametrize("command", [
    "cd build; rm -rf *", "cd build\nrm -rf *", "cd build || true; rm -rf *", "cd /tmp/nonexistent-build; rm -rf *", "(cd /tmp/x); rm -rf *",
    "cd build & rm -rf *", "cd build || rm -rf *", "pushd build; rm -rf .", "cd /tmp/x ; rm -rf ./..",
])
def test_a_cd_not_joined_by_and_leaves_the_directory_unknown(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "cd /tmp/x; rm -rf *", "cd /tmp/x\nrm -rf *", "cd /tmp/x || true; rm -rf *", "cd /tmp/x & rm -rf *",
])
def test_a_cd_not_joined_by_and_is_judged_against_both_directories(command):
    assert allowed_in(command)                      # round 5: both /tmp/x and the request directory src/x are safe
    assert not allowed_in(command, HOME)            # the request directory is home: the failed-cd case reaches it


@pytest.mark.parametrize("command", [
    "cd build && rm -rf *", "cd build || exit 1; rm -rf *", "cd /tmp/x && rm -rf *", "cd /tmp/x || exit; rm -rf *",
    "(cd /tmp/x && rm -rf *)", "cd /tmp/x && cd y && rm -rf *", "cd /tmp/x && (rm -rf *)", "cd /tmp/x && { rm -rf *; }",
])
def test_a_cd_joined_by_and_or_followed_by_exit_is_judged_against_its_directory(command):
    assert allowed_in(command, HOME)               # judged against its own directory, not the request directory


def test_cd_to_the_home_directory_is_still_critical_when_joined_by_and():
    assert not allowed_in("cd ~ && rm -rf *", HOME + "/src/x")
    assert not allowed_in("cd ~ || exit; rm -rf *", HOME + "/src/x")
    assert not allowed_in("cd / && rm -rf ?*", HOME + "/src/x")


def test_a_subshell_or_a_pipeline_stage_gives_the_outer_directory_back():
    assert allowed_in("(cd ~ && ls); rm -rf *")                      # the outer directory is src/x again
    assert not allowed_in("(cd /tmp/x && ls); rm -rf *", HOME)       # and it is home here
    assert allowed_in("cd ~ | cat; rm -rf *")
    assert not allowed_in("cd ~ | cat; rm -rf *", HOME)
    assert allowed_in("echo | cd ~; rm -rf *")
    assert allowed_in("(cd /tmp/x; ls) && rm -rf *")
    assert not allowed_in("(cd /tmp/x && ls) && rm -rf *", HOME)


# item 2 (MED-2): find from an unknown directory needs a narrowing name test

@pytest.mark.parametrize("command", [
    "find . -type f -delete", "find . -mtime +7 -delete", "find . -size +0 -delete", "find . -newer x -delete", "find . -name '*' -delete",
    "find . -user tester -exec rm -rf {} +", "find . -type f -exec rm {} \\;", "find . -type f -execdir rm {} \\;", "find . -perm 600 -delete",
    "find . ! -name keep -delete", "find . -name a -o -type f -delete", "find . -name '*.*' -delete", "find . -name '?' -delete", "find . -name '*..' -delete", "find . -name '*x' -delete", "find . -name 'a*' -exec rm {} +",
    "find . -type f | xargs rm", "find . -type f -print0 | xargs -0 rm", "find . -type f -name '*' -exec rm {} +",
])
def test_find_from_an_unknown_directory_without_a_narrowing_name_is_held(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "find . -name '*.pyc' -delete", "find . -name __pycache__ -type d -exec rm -rf {} +", "find . -type d -empty -delete",
    "find . -name node_modules -exec rm -rf {} +", "find . -iname '*.log' -delete",
    "find . -name 'core.*' -delete", "find build -type f -delete", "find ./build -mtime +7 -delete", "find . -name x -delete",
    "find . -name '*.pyc' -print0 | xargs -0 rm",
])
def test_find_from_an_unknown_directory_with_a_narrowing_name_is_allowed(command):
    assert held(command).allow, (command, held(command).rule)


def test_find_from_a_known_directory_is_judged_against_it():
    assert allowed_in("find . -type f -delete")
    assert not allowed_in("find . -type f -delete", HOME)
    assert allowed_in("cd /tmp/x && find . -type f -delete", HOME)
    assert not allowed_in("cd /tmp/x; find . -type f -delete", HOME)


# item 3 (LOW): `${X:?}`, `${X:=...}`, sourced files, runners, mv, git commands

@pytest.mark.parametrize("command", [
    'rm -rf "${HOME:?}"', 'rm -rf "${HOME?}"', 'rm -rf "${S:?}"/x', "rm -rf ${S:?}", ": ${D:=~}; rm -rf $D", ": ${D=~}; rm -rf $D",
    ": ${D:=/}; rm -rf $D/", "rm -rf ${D:=~}",
])
def test_the_error_and_assign_forms_of_a_variable_are_unknown(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "source env.sh; rm -rf $S/", ". ./env.sh; rm -rf $BUILD", "set -a; rm -rf $S/x", "export $(cat env); rm -rf $S", "x=1; . ./e; rm -rf $S/*.log",
    "cd /tmp && source e && rm -rf $S/*.log", "(. e; rm -rf $S/)", "source e\nrm -f $S/all.done $S/*.log",
])
def test_a_line_that_sources_a_file_makes_every_variable_unknown(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", ["source e; rm -rf $HOME/src/x", "source e; rm -rf ./build", "source e; rm -rf /tmp/x", "echo source e"])
def test_sourcing_leaves_home_and_variable_free_removals_alone(command):
    assert held(command).allow, (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "uv run python -c 'import shutil; shutil.rmtree(\"x\")'", "uvx python -c 'import os; os.remove(1)'", "pipx run python3 -c 'p.unlink()'",
    "poetry run python -c 'import shutil; shutil.rmtree(1)'", "npx node -e \"require('fs').rmSync('x')\"", "bunx bun -e 'fs.unlinkSync(1)'",
    "pnpm exec node -e 'fs.rmSync(1)'", "uv run python - <<'PY'\nimport shutil; shutil.rmtree('x')\nPY", "uv run --with x python -c 'os.unlink(1)'",
])
def test_runners_of_interpreters_get_the_one_liner_check(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "uv run python -c 'print(1)'", "uv run pytest tests", "uvx ruff check .", "npx prettier --write .", "poetry run python script.py", "pipx run black x",
    "uv run python -m pytest -k remove",
])
def test_ordinary_runner_calls_stay_allowed(command):
    assert held(command).allow, (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "mv ~ /tmp/gone", "mv ~/Library ~/L.old", "mv /Users/tester /tmp/x", "mv -t /tmp/x ~", "mv /Applications /tmp/a", "mv /etc /tmp/e", "mv ~/* /tmp/old",
    "mv -f ~ /tmp/gone", "mv -- ~ /tmp/gone", "mv $HOME /tmp/x", "mv /Users/tester/Library/Application\\ Support /tmp/a", "gmv ~ /tmp/x",
    "mv --target-directory=/tmp/x ~", "mv *.log ~/ ; mv * /tmp/x",
])
def test_moving_a_critical_directory_is_held(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "mv a b", "mv ~/x.log /tmp/y", "mv -t /tmp/dst a b", "mv ~/old /tmp", "mv /tmp/a /tmp/b", "mv -f build/out dist", "mv ~/src/x ~/src/y",
    "mv /tmp/x ~", "mv a.log ~/logs/", "mv -n a /Applications", "mv -t /tmp a b", "mv -t ~ x", "mv --target-directory ~/ x", "mv --target-directory=/tmp a",
])
def test_ordinary_moves_stay_allowed(command):
    assert held(command).allow, (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "git submodule foreach 'rm -rf ~'", "git -c alias.x='!rm -rf ~' x", "git rebase --exec 'rm -rf x' main", "git rebase -x 'rm x' main", "git rebase --exec='rm x' main",
    "git bisect run rm x", "git submodule foreach --recursive 'rm -rf x'", "git -C ~/src/x submodule foreach 'trash x'", "git -c alias.go='!trash x' go",
])
def test_git_commands_that_run_a_command_line_are_read_for_removers(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "git submodule foreach 'git pull'", "git rebase --exec 'make test' main", "git -c alias.x='!echo hi' x", "git commit -m 'rm -rf handling'",
    "git rm -rf --cached x", "git log --grep=rm", "git bisect run make test",
])
def test_git_commands_without_a_remover_stay_allowed(command):
    assert held(command).allow, (command, held(command).rule)


# item 3 (LOW-4): the extension glob exception only below `/` and the temp directories

@pytest.mark.parametrize("command", [
    "rm -rf /Applications/*.app", "rm -rf ~/*.app", "rm -rf /System/Library/*.plist", "rm -rf /Library/*.plist", "rm -rf /Users/*.app",
    "rm -f ~/*.log", "rm -f /Users/tester/*-old.txt", "rm -rf /Users/tester/{a,b}.log", "rm -rf /usr/local/*.txt", "rm -rf /opt/*.app",
    "rm -rf /tmp/*", "rm -rf /tmp/c*", "rm -rf /tmp/.*", "rm -rf /private/tmp/*", "rm -rf /tmp/?", "rm -rf /tmp/.hidden*", "rm -rf /tmp/{a,b}*",
    "rm -rf /tmp/[a-z]*", "rm -rf /private/tmp/*-*",
])
def test_extension_and_stem_globs_do_not_narrow_critical_top_directories(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "rm -rf /tmp/claude-*", "rm -rf /private/tmp/claude-*", "rm -f /tmp/pytest-*.log", "rm -rf /tmp/prefix-*", "rm -f /*.log", "rm -f /tmp/*.log",
    "rm -rf /private/tmp/build-*/x", "rm -rf /tmp/ade-?", "rm -f /private/tmp/a.b*",
])
def test_stem_globs_below_the_temp_directories_and_extensions_below_slash_are_allowed(command):
    assert held(command).allow, (command, held(command).rule)


# item 4: values of variables set once on the line

@pytest.mark.parametrize("command", [
    "S=$(mktemp -d); rm -rf \"$S\"", "S=$(mktemp -d); touch $S/a; rm -rf \"$S\"/*", "S=$(mktemp -d /tmp/x.XXXX); rm -rf $S", "S=$(mktemp); rm -f $S",
    "S=\"$(mktemp -d)\"; rm -rf \"$S\"", "S=`mktemp -d`; rm -rf $S", "S=$(mktemp -d)/sub; rm -rf $S", "export S=$(mktemp -d); rm -rf $S/*",
    "S=/private/tmp/claude-502/x; rm -f $S/*.log", "S=/tmp/x; rm -f $S/a $S/*.log", "for f in a.log b.log; do rm -f \"$f\"; done",
    "export S=/tmp/x; rm -rf $S", "S=/tmp/a; T=$S/b; rm -rf $T", "declare -x S=/tmp/x; rm -rf $S/*", "S=/tmp/x\nrm -rf $S", "S=/tmp/x && rm -rf $S",
    "(S=/tmp/x; rm -rf $S)", "S=/tmp/x; rm -rf ${S}/a", "D=build; rm -rf $D/out",
    "for d in /tmp/a /tmp/b; do rm -rf $d; done", "for f in a b c; do rm -f $f.log; done", "S=~/src/x-wt; rm -rf $S/*", "S=$HOME/src/x; rm -rf $S",
    "bash -c 'S=$(mktemp -d); rm -rf $S'", "S=/tmp/x; cd $S && rm -rf *",
])
def test_variables_set_once_to_a_literal_or_a_fresh_temp_path_are_judged_on_their_value(command):
    assert held(command).allow, (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "S=/; rm -rf $S", "S=/tmp; rm -rf $S/", "S=/tmp; rm -rf $S/*", "S=~; rm -rf $S", "D=$HOME; rm -rf $D", "S=$HOME/Library; rm -rf $S",
    "for d in /tmp/a /; do rm -rf $d; done", "for d in ~ /tmp/a; do rm -rf \"$d\"; done", "for d in /Users /tmp/a; do rm -rf $d/*; done",
    "S=/tmp/x; S=/; rm -rf $S", "true && S=/tmp/x; rm -rf $S/", "if true; then S=/tmp/x; fi; rm -rf $S/", "(S=/tmp/x); rm -rf $S/",
    "S=/tmp/x | cat; rm -rf $S", "S=/tmp/x & rm -rf $S/", "S=$(echo /); rm -rf $S", "S=$(mktemp -d) rm -rf $S/", "rm -rf $S/; S=/tmp/x",
    "S=/tmp/x; unset S; rm -rf $S/", "source e; S=/tmp/x; rm -rf $S", "S=/tmp/x; S+=/y; rm -rf $S", "S=/tmp/x; read S; rm -rf $S",
    "for f in *; do rm -rf $f; done", "for f in $(ls); do rm -rf $f; done", "for f in a $X; do rm -rf $f; done", "for f in a; do rm -rf $f; done; f=/; rm -rf $f",
    "S=/tmp/x; rm -rf ${S:-/}", "S=/tmp/$X; rm -rf $S", "S=\"/tmp/a b\"; rm -rf $S", "S=-rf; rm $S x", "A=/; B=$A; rm -rf $B",
    "S=$(mktemp -d)$X; rm -rf $S", "S=$(mktemp -d); T=$(echo /); rm -rf $T", "S=$(mktemp -d \"$(echo ~)\"); rm -rf $S", "S=/tmp/x; rm -rf $SS/", "S=$X/y; X=/; rm -rf $S",
    "echo $(S=/tmp/x; true); rm -rf $S/", "for d in /tmp/a /; do cd $d && rm -rf *; done", "for d in " + " ".join("a%d" % i for i in range(40)) + "; do rm -rf $d; done", "S=$(mktemp -d && echo /); rm -rf $S",
    "S=$(mktemp -d; rm -rf ~); echo $S", "S=/; cd $S && rm -rf *",
])
def test_other_assignments_and_critical_values_stay_held(command):
    assert is_held(command), (command, held(command).rule)


def test_critical_values_are_reported_as_critical_removals():
    assert held("S=/; rm -rf $S").rule.startswith("critical-rm:")
    assert held("S=/; rm -rf ${S}").rule.startswith("critical-rm:")
    assert "too many values" in held("for d in " + " ".join("a%d" % i for i in range(40)) + "; do rm -rf $d; done").rule
    assert held("for d in /tmp/a /; do rm -rf $d; done").rule.startswith("critical-rm:")
    assert held("HOME=/ ; rm -rf $HOME").rule.startswith("critical-rm:")
    assert held("rm -rf $S/; S=/tmp/x").rule.startswith("unreadable:unparsable:variable $S")


# ---------------------------------------------------------------- adversary round 4 (PR 939), fixed in round 5


def held_everywhere(command):
    """Held with no request directory and with the request directory at home."""
    return is_held(command) and not allowed_in(command, HOME)


# MED-1: a cd's directory holds only while `&&` (or a pipe) keeps joining the statements

@pytest.mark.parametrize("command", [
    "cd /tmp/x && ls; rm -rf *", "cd /tmp/x && make\nrm -rf *", "cd /tmp/x && make || true; rm -rf *", "cd /tmp/x && (make); rm -rf *",
    "cd /tmp/x && { make; }; rm -rf *", "cd /tmp/x && true\nrm -rf .", "cd /tmp/x && rm -rf * ; rm -rf ./*",
    "cd /tmp/x && find . -type f -delete; find . -type f -delete", "pushd /tmp/x && ls; rm -rf *",
    "cd /tmp/x && ls & rm -rf *", "cd /tmp/x && ls && make; rm -rf *",
])
def test_statements_after_a_cd_chain_that_ended_are_in_an_unknown_directory(command):
    assert held_everywhere(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "cd /tmp/x && ls && rm -rf *", "cd /tmp/x && ls | cat && rm -rf *", "cd /tmp/x && (ls) && rm -rf *", "cd /tmp/x &&\nrm -rf *",
    "cd /tmp/x && ls &&\nrm -rf *", "cd /tmp/x || exit\nrm -rf *", "cd /tmp/x && ls && make && rm -rf *",
])
def test_a_cd_chain_joined_all_the_way_is_judged_in_its_directory(command):
    assert allowed_in(command, HOME), (command, held(command).rule)


def test_a_cut_chain_is_judged_against_both_known_directories():
    assert allowed_in("cd /tmp/x && ls; rm -rf *")                    # request directory src/x and /tmp/x: both safe
    assert not allowed_in("cd /tmp/x && ls; rm -rf *", HOME)          # the failed cd leaves it in home
    assert allowed_in("cd build && ls; rm -rf *")
    assert not allowed_in("cd ~ && ls; rm -rf *")                     # the new directory itself is critical


# MED-2: find narrows only through tests that come before the first action

@pytest.mark.parametrize("command", [
    "find . -delete -name '*.pyc'", "find . -exec rm -rf {} + -name '*.pyc'", "find . -delete -empty", "find . -true -delete -name x",
    "find . -name '*.pyc' , -delete", "find . -name x -print , -delete", "find . -execdir rm {} + -name x", "find . -ok rm {} \\; -name x",
])
def test_find_tests_after_the_action_or_a_comma_do_not_narrow(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "find . -name '*.pyc' -delete", "find . -name x -print -delete", "find . -type f -name '*.pyc' -exec rm {} +", "find . -empty -delete",
])
def test_find_tests_before_the_action_still_narrow(command):
    assert held(command).allow, (command, held(command).rule)


# MED-3 (a): an assignment inside a compound command or after a joining line break is not unconditional

@pytest.mark.parametrize("command", [
    'if [ -n "$CI" ]; then\nD=/tmp/ci-cache\nfi\nrm -rf "$D"/*', 'if [ -n "$CI" ]; then\nD=/tmp/ci-cache\nfi\nrm -rf "$D"/',
    'while false; do\nD=/tmp/x\ndone\nrm -rf "$D"/*', '[ -d /tmp/x ] &&\nD=/tmp/x\nrm -rf "$D"/*', 'false ||\nD=/tmp/x\nrm -rf "$D"/*',
    'until true; do\nD=/tmp/x\ndone\nrm -rf "$D"/*', 'for i in 1 2; do\nD=/tmp/x\ndone\nrm -rf "$D"/*',
    'case $X in\na) D=/tmp/x;;\nesac\nrm -rf "$D"/*', 'if true; then\nD=/tmp/x\nelse\nD=/tmp/y\nfi\nrm -rf "$D"/*',
    'true |\nD=/tmp/x\nrm -rf "$D"/*',
])
def test_an_assignment_in_a_compound_body_or_after_a_joining_newline_is_unknown(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    'if true; then echo hi; fi\nD=/tmp/x\nrm -rf "$D"/*', 'for i in 1; do echo $i; done\nS=$(mktemp -d)\nrm -rf "$S"',
    'case a in a) echo;; esac\nD=/tmp/x\nrm -rf $D',
])
def test_an_assignment_after_the_compound_command_ended_is_tracked_again(command):
    assert held(command).allow, (command, held(command).rule)


def test_a_line_break_after_and_joins_the_next_statement_to_the_chain():
    assert allowed_in("cd /tmp/x &&\nrm -rf *", HOME)               # was a false hold before round 5
    assert allowed_in("cd /tmp/x && ls &&\nrm -rf *", HOME)
    assert not allowed_in("cd /tmp/x &&\nls\nrm -rf *", HOME)       # the second line break does end the chain


# MED-3 (b): a child shell sees no value tracked in the outer line

@pytest.mark.parametrize("command", [
    "S=/tmp/x; bash -c 'rm -rf \"$S\"/*'", "S=/tmp/x; sh -c 'rm -rf $S/'", "S=/tmp/x; nohup bash -c 'rm -rf \"$S\"/*'",
    "S=/tmp/x; sudo bash -c 'rm -rf \"$S\"/*'", "export S=/tmp/x; sudo bash -c 'rm -rf \"$S\"/*'",
    "S=/tmp/x; timeout 60 bash -c 'rm -rf \"$S\"/*'", "S=/tmp/x; env bash -c 'rm -rf \"$S\"/*'", "S=/tmp/x; zsh -c 'rm -rf \"$S\"/*'",
    "S=/tmp/x; env -S 'rm -rf $S/'",
])
def test_a_child_shell_body_does_not_see_the_outer_tracked_values(command):
    assert is_held(command), (command, held(command).rule)


def test_a_child_shell_tracks_the_names_it_sets_itself():
    assert held("bash -c 'S=$(mktemp -d); rm -rf $S'").allow
    assert held("bash -c 'S=/tmp/x; rm -rf \"$S\"/*'").allow
    assert held("S=/tmp/x; rm -rf \"$S\"/*").allow                  # the outer line is unchanged


# LOW-1: only exit leaves at the top level; return needs a function, break and continue need a loop

@pytest.mark.parametrize("command", [
    "cd /tmp/x || return; rm -rf *", "cd /tmp/x || break; rm -rf *", "cd /tmp/x || continue; rm -rf *", "cd /tmp/x || return 1; rm -rf *",
])
def test_return_break_and_continue_outside_a_function_or_loop_do_not_leave(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "cd /tmp/x || exit; rm -rf *", "cd /tmp/x || exit 1; rm -rf *", "for d in a b; do cd /tmp/x || continue; rm -rf *; done",
    "while true; do cd /tmp/x || break; rm -rf *; done",
])
def test_exit_always_and_break_or_continue_inside_a_loop_leave(command):
    assert allowed_in(command, HOME), (command, held(command).rule)


# LOW-2: an array assignment is not an empty literal

@pytest.mark.parametrize("command", [
    "arr=(~ /tmp/x); rm -rf $arr", "arr=(/ /tmp/x); rm -rf $arr", "declare -a arr=(~); rm -rf $arr", "arr=(); rm -rf $arr/",
    "local -a arr=(/); rm -rf ${arr[0]}",
])
def test_an_array_assignment_is_unknown(command):
    assert is_held(command), (command, held(command).rule)


# LOW-3: a glob followed by `..`, sourcing after a keyword, more remover words

@pytest.mark.parametrize("command", [
    "rm -rf /tmp/cl*/../../../Users/tester", "rm -rf /tmp/*.log/../..", "rm -rf /tmp/a*/../../..", "rm -rf ~/src/*/../..",
])
def test_a_glob_followed_by_dotdot_is_judged_by_its_whole_path(command):
    assert is_held(command), (command, held(command).rule)


def test_a_glob_that_stays_narrow_after_dotdot_is_still_allowed():
    assert held("rm -rf /tmp/claude-*.log").allow


@pytest.mark.parametrize("command", [
    'if source ./env.sh; then rm -rf "$OUT"; fi', 'true && ! source ./env.sh; rm -rf "$OUT"', 'time source ./env.sh; rm -rf "$OUT"',
    'while source ./env.sh; do rm -rf "$OUT"; done', 'if true; then source ./env.sh; rm -rf "$OUT"; fi',
    'for i in 1; do . ./env.sh; rm -rf "$OUT"; done', 'until source ./env.sh; do rm -rf "$OUT"/*; done',
    'if true; then\nsource ./env.sh\nfi\nrm -rf "$OUT"',
])
def test_sourcing_after_a_shell_keyword_makes_every_name_unknown(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "npx rimraf ~", "npx del-cli ~", "rimraf /", "npx rimraf '/Users/*'", "pnpm dlx del-cli /", "bunx rimraf ~/Library",
])
def test_rimraf_and_del_cli_are_removers(command):
    assert is_held(command), (command, held(command).rule)


def test_rimraf_and_del_cli_are_never_judged_so_every_form_keeps_the_card():
    assert is_held("rimraf node_modules")                 # remover words the parser does not judge: held whatever the operand (fails safe)
    assert is_held("npx rimraf dist")
    assert is_held("del-cli build")


# LOW-4: a fresh mktemp path is a removal operand only, never a cd target

@pytest.mark.parametrize("command", [
    'S=$(mktemp -d); cd "$S" && rm -rf *', "S=$(mktemp -d); cd $S && rm -rf .", "S=`mktemp -d`; cd \"$S\" && rm -rf *",
    'S=$(mktemp -d); pushd "$S" && rm -rf *',
])
def test_a_mktemp_path_is_not_a_cd_target(command):
    assert is_held(command), (command, held(command).rule)


def test_a_mktemp_path_is_still_a_removal_operand():
    assert held('S=$(mktemp -d); rm -rf "$S"').allow
    assert held('S=$(mktemp -d); touch "$S/a"; rm -rf "$S"/*').allow


# round 5: survivors of the first mutation pass, killed

@pytest.mark.parametrize("command", [
    "ssh host rimraf dist", "parallel del-cli ::: build", "xargs -J {} rimraf {}", "ssh host 'rimraf dist'", "ssh host 'cd x && del-cli build'",
])
def test_rimraf_and_del_cli_are_remover_words_for_the_tripwire(command):
    assert is_held(command), (command, held(command).rule)


def test_a_chain_cut_many_times_gives_up_on_the_alternatives():
    many = "".join("cd /tmp/d%d && ls; " % i for i in range(10))
    assert allowed_in("cd /tmp/d0 && ls; rm -rf *")
    assert not allowed_in(many + "rm -rf *")                          # more than 8 alternative directories: unknown


def test_a_later_cd_chain_forgets_the_alternatives_of_the_earlier_one():
    assert allowed_in("cd /tmp/a && ls; cd /tmp/b && rm -rf *", HOME)  # a failed second cd skips the rm


def test_a_cd_cut_by_a_semicolon_is_not_a_certain_directory_even_before_a_break():
    assert not allowed_in("for i in 1; do cd /tmp/x; break; done; rm -rf *", HOME)


def test_break_after_a_finished_loop_does_not_leave():
    assert is_held("for i in 1; do :; done; cd /tmp/x || break; rm -rf *")
    assert is_held("while false; do :; done\ncd /tmp/x || continue; rm -rf *")


def test_a_substitution_body_does_not_leak_its_cut_chain_alternatives():
    assert allowed_in("echo $(cd /tmp/a && ls; true); rm -rf *")


def test_an_if_inside_an_if_keeps_the_assignment_after_the_inner_fi_conditional():
    assert is_held('if true; then if true; then echo; fi\nD=/tmp/x\nfi\nrm -rf "$D"/*')
    assert is_held('if true; then\nwhile false; do :; done\nD=/tmp/x\nfi\nrm -rf "$D"/*')
    assert is_held('while true; do for i in 1; do :; done\nD=/tmp/x\ndone\nrm -rf "$D"/*')


def test_values_come_back_after_a_child_shell_body():
    assert held("S=/tmp/x; bash -c 'echo hi'; rm -rf \"$S\"/*").allow


@pytest.mark.parametrize("command", [
    'f() { :; }; S=/tmp/x; rm -rf "$S"/*', 'alias ll=ls; S=/tmp/x; rm -rf "$S"/*', 'function g { :; }; S=/tmp/x; rm -rf $S',
])
def test_a_request_that_defines_a_function_or_alias_tracks_no_values(command):
    assert is_held(command), (command, held(command).rule)


# ---------------------------------------------------------------- adversary round 5 (PR 939), fixed in round 6

SRC_X = HOME + "/src/x"


def held_in_all_three(command):
    return is_held(command) and not allowed_in(command, HOME) and not allowed_in(command, SRC_X)


# MED-1: a brace group joined by `&&` or `||` and written over several lines is conditional

@pytest.mark.parametrize("command", [
    '[ -d /tmp/x ] && {\nD=/tmp/x\n}\nrm -rf "$D"/*',
    '[ -n "$CI" ] && {\n  OUT=/tmp/ci-out\n  mkdir -p "$OUT"\n}\nrm -rf "$OUT"/*',
    '[ -n "$CI" ] || {\nD=/tmp/x\n}\nrm -rf $D/*',
    'command -v foo >/dev/null || {\n  D=/tmp/x\n}\nrm -rf "$D"/',
    '{ if [ -n "$CI" ]; then\nD=/tmp/x\nfi\n}\nrm -rf "$D"/*',
    '[ -n "$CI" ] && { D=/tmp/x; }; rm -rf "$D"/*',
    '{ { [ -n "$CI" ] && {\nD=/tmp/x\n}\n}\n}\nrm -rf "$D"/*',
])
def test_an_assignment_in_a_brace_group_is_unknown(command):
    assert held_in_all_three(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    '[ -n "$CI" ] && {\n  echo hi\n}\nD=/tmp/x\nrm -rf "$D"/*', '{\n  echo hi\n}\nS=$(mktemp -d)\nrm -rf "$S"',
    '{ if true; then\n  echo\nfi\n}\nD=/tmp/x\nrm -rf "$D"',
])
def test_an_assignment_after_the_brace_group_ended_is_tracked_again(command):
    assert held(command).allow, (command, held(command).rule)


# LOW-1: every directory a live cd chain leaves is an alternative

@pytest.mark.parametrize("command", [
    "cd ~ && cd build; rm -rf *", "cd ~ && ls && cd build; rm -rf *", "cd ~ && cd build && make; rm -rf *", "cd ~ && cd build\nrm -rf *",
    "cd ~ && cd build || true; rm -rf *", "cd / && cd tmp/x; rm -rf *", "cd ~/Library && cd Caches/foo; rm -rf *",
])
def test_the_directory_a_second_cd_leaves_is_an_alternative(command):
    assert not allowed_in(command, SRC_X), command
    assert is_held(command), command


def test_a_two_step_cd_chain_that_stays_joined_is_judged_in_the_last_directory():
    assert allowed_in("cd /tmp/a && cd b && rm -rf *", SRC_X)
    assert allowed_in("cd /tmp/a && cd /tmp/b && ls && rm -rf *", HOME)


# LOW-2: the certainty of `cd X || break` ends with the loop

@pytest.mark.parametrize("command", [
    'for d in /tmp/a; do cd "$d" || break; done; rm -rf *', 'for d in /tmp/a; do cd /tmp/a || continue; done; rm -rf *',
    "while true; do cd /tmp/a || break; done\nrm -rf *",
])
def test_a_break_certainty_does_not_outlive_the_loop(command):
    assert is_held(command) and not allowed_in(command, HOME), command


# LOW-3: print before the name test feeds every path to xargs

@pytest.mark.parametrize("command", [
    "find . -print0 -name x | xargs -0 rm", "find . -print -name '*.pyc' | xargs rm", "find . -ls -name x | xargs rm",
    "find . -printf '%p\\n' -name x | xargs rm",
])
def test_a_print_before_the_name_test_gives_xargs_every_path(command):
    assert is_held(command), (command, held(command).rule)


def test_a_print_after_the_name_test_still_narrows():
    assert held("find . -name '*.pyc' -print0 | xargs -0 rm").allow


# LOW-4: git clean through the alternatives

def test_git_clean_is_judged_against_every_possible_directory():
    assert not allowed_in("cd /tmp/x && ls; git clean -fdx", HOME)
    assert allowed_in("cd /tmp/x && ls; git clean -fdx", SRC_X)
    assert not allowed_in("git clean -fdx", HOME)


# LOW-5: a body is not judged in the directory the line starts in once a cd is on the line

@pytest.mark.parametrize("command", [
    "cd ~ && x=$(find . -delete)", 'cd ~ && echo "$(rm -rf *)"', "cd ~; echo `rm -rf *`",
])
def test_a_substitution_body_after_a_cd_has_an_unknown_directory(command):
    assert not allowed_in(command, SRC_X), command


def test_a_substitution_body_without_a_cd_keeps_the_request_directory():
    assert allowed_in('echo "$(rm -rf *)"', SRC_X)
    assert allowed_in('cd /tmp/x && git commit -m "$(cat <<EOF\nmsg\nEOF\n)"', SRC_X)


# LOW-6: a `)` gives the alternatives back

def test_a_group_end_restores_the_alternatives():
    assert not allowed_in("cd /tmp/x && ls; (cd /tmp/y && ls); rm -rf *", HOME)
    assert not allowed_in("cd /tmp/x && ls\n(cd /tmp/y && ls)\nrm -rf *", HOME)
    assert allowed_in("cd /tmp/x && ls; (cd /tmp/y && ls); rm -rf *", SRC_X)


# round 6: survivors of the first mutation pass, killed

def test_a_group_around_an_if_stays_conditional_after_the_inner_fi():
    assert held_in_all_three('{ if [ -n "$CI" ]; then\n  echo\nfi\nD=/tmp/x\n}\nrm -rf "$D"/*')


def test_exit_in_a_loop_keeps_the_certain_directory_after_the_loop():
    assert allowed_in("for d in a; do cd /tmp/x || exit; done; rm -rf *", HOME)


@pytest.mark.parametrize("command", ['pushd ~ && echo "$(rm -rf *)"', 'popd; echo "$(rm -rf *)"'])
def test_a_body_after_pushd_or_popd_has_an_unknown_directory(command):
    assert not allowed_in(command, SRC_X), command


def test_a_print_before_the_name_test_without_xargs_still_narrows_the_delete():
    assert held("find . -print -name x -delete").allow


def test_git_clean_with_its_own_directory_ignores_the_alternatives():
    assert allowed_in("cd /tmp/x && ls; git -C /tmp/y clean -fdx", HOME)
    assert not allowed_in("cd /tmp/x && ls; git clean -fdx", HOME)


# ---------------------------------------------------------------- adversary round 6 (PR 939), fixed in round 7

# MED: the positional parameters of a shell body fed by xargs are unknown, not empty

@pytest.mark.parametrize("command", [
    "find \"$OUT\"/ -mindepth 1 -print0 | xargs -0 sh -c 'rm -rf \"$@\"' _", "find ~ -print0 | xargs -0 sh -c 'rm -rf \"$@\"' _",
    "find ~ -print0 | xargs -0 bash -c 'rm -rf \"$@\"' _", "find ~ -print0 | xargs -0 sh -c 'rm -rf $*' _",
    "find ~ -print0 | xargs -0 sh -c 'for f in \"$@\"; do rm -rf \"$f\"; done' _", "ls -A | xargs sh -c 'rm -rf \"$@\"' _",
    "find . -mindepth 1 -maxdepth 1 -print0 | xargs -0 sh -c 'rm -rf \"$@\"' _", "echo ~ | xargs sh -c 'rm -rf \"$@\"' _",
    "cat list | xargs sh -c 'rm -rf \"$@\"' _", "find / -maxdepth 1 -print0 | xargs -0 sh -c 'chmod -R 777 \"$@\"' _",
    "find ~ -print0 | xargs -0 -n1 sh -c 'rm -rf \"$1\"' _", "find ~ -print0 | xargs -0 sudo sh -c 'rm -rf \"$@\"' _",
    "find ~ -print0 | xargs -0 nohup sh -c 'rm -rf \"$@\"' _", "find ~ -print0 | xargs -0 sh -c 'rm -rf \"${@}\"' _",
    "find ~ -print0 | xargs -0 sh -c 'rm -rf \"$@\"'",
])
def test_an_xargs_fed_shell_body_judges_the_feed(command):
    assert is_held(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "find build -name '*.o' -print0 | xargs -0 sh -c 'rm -f \"$@\"' _",
    "find . -name '*.pyc' -print0 | xargs -0 sh -c 'rm -f \"$@\"' _",
    "find . -print0 | xargs -0 sh -c 'echo \"$@\"' _",
])
def test_an_xargs_fed_shell_body_with_a_narrowed_feed_or_no_removal_stays_allowed(command):
    assert held(command).allow, (command, held(command).rule)


def test_a_shell_body_with_given_parameters_is_unchanged():
    assert is_held("sh -c 'rm -rf \"$@\"' _ ~")
    assert held("sh -c 'rm -rf \"$1\"' _ /tmp/x/a").allow
    assert held("sh -c 'rm -rf \"$2\"' _ /tmp/x/a").allow             # no xargs: a missing positional is empty and harmless


# LOW-1: a body is scanned with the line's directory and again with none

def test_a_body_before_a_later_cd_is_still_judged_in_the_request_directory():
    assert not allowed_in('n=$(find . -name "*.log" -delete -print | wc -l); cd ~/src/x && make', HOME)
    assert not allowed_in("x=$(rm -rf Library); cd /tmp", HOME)
    assert not allowed_in("x=$(rm -rf *); cd /tmp", SRC_X)


# LOW-2: git clean after a chain that began in an unknown directory

@pytest.mark.parametrize("command", [
    "cd ~ && ls; git clean -fdx", "cd ~; git clean -fdx", "cd ~ && make; git clean -fdx", "cd ~/Library && ls; git clean -fdx",
    "cd / && ls\ngit clean -fdx",
])
def test_git_clean_after_a_broken_chain_from_an_unknown_directory_is_held(command):
    assert is_held(command), (command, held(command).rule)


def test_git_clean_after_a_safe_broken_chain_from_an_unknown_directory_is_allowed():
    assert held("cd /tmp/x && ls; git clean -fdx").allow


# ---------------------------------------------------------------- adversary round 7 (PR 939), fixed in round 8

def held_in_three_modes(command):
    return is_held(command) and not allowed_in(command, HOME) and not allowed_in(command, SRC_X)


@pytest.mark.parametrize("command", [
    "find \"$OUT\"/ -mindepth 1 -maxdepth 1 | xargs -I{} sh -c 'rm -rf \"{}\"'",
    "find \"$OUT\"/ -mindepth 1 -maxdepth 1 -print0 | xargs -0 -I{} sh -c 'rm -rf \"{}\"'",
    "find ~ | xargs -I{} sh -c 'rm -rf \"$1\"' _ {}", "find ~ | xargs -I{} bash -c 'echo removing {}; rm -rf \"{}\"'",
    "find / -maxdepth 1 | xargs -I{} sh -c 'chmod -R 777 {}'", "ls -d */ | xargs -I{} sh -c 'rm -rf {}'", "cat list | xargs -I{} sh -c 'rm -rf {}'",
    "find ~ | xargs -i sh -c 'rm -rf {}'", "find ~ | xargs --replace sh -c 'rm -rf {}'", "find ~ | xargs -I{} sh -c 'rm -rf {}/build'",
    "find ~ | xargs -I % sh -c 'rm -rf \"%\"'", "find ~ | xargs -I% sh -c 'rm -rf %'", "find ~ | xargs -I FILE sh -c 'rm -rf FILE'",
    "echo ~ | xargs -I % sh -c 'rm -rf \"%\"'", "find ~ -print0 | xargs -I % sh -c 'rm -rf \"$1\"' _ %",
    "find ~ | xargs -I{} sh -c 'unlink {}'", "find ~ | xargs -I{} sh -c 'find \"$1\" -delete' _ {}", "find ~ | xargs -I{} sh -c 'cd \"$1\" && rm -rf *' _ {}",
])
def test_an_xargs_replace_string_in_a_shell_body_judges_the_feed(command):
    assert held_in_three_modes(command), (command, held(command).rule)


def test_a_narrowed_feed_with_a_replace_string_or_a_zero_positional_stays_allowed():
    assert held("find build -name '*.o' -print0 | xargs -0 -n1 sh -c 'rm -f \"$0\"'").allow
    assert allowed_in("find build -name '*.o' -print0 | xargs -0 -I{} sh -c 'rm -f \"{}\"'", SRC_X)     # `{}` is a broad glob when the directory is unknown
    assert held("printf '%s\\n' build dist | xargs -n1 sh -c 'rm -rf \"$0\"'").allow


@pytest.mark.parametrize("command", [
    "find ~ -print0 | xargs -0 -n1 sh -c 'git -C \"$1\" clean -fdx' _", "find ~ -print0 | xargs -0 -n1 sh -c 'git -C \"$0\" clean -fdx'",
    "find ~ | xargs -I{} sh -c 'git -C {} clean -fdx'", "find ~ | xargs -I{} git -C {} clean -fdx",
])
def test_an_xargs_fed_git_clean_is_held(command):
    assert held_in_three_modes(command) or is_held(command), (command, held(command).rule)
    assert not allowed_in(command, HOME), command


@pytest.mark.parametrize("command", [
    "find ~ -print0 | xargs -0 sh -c 'mv \"$@\" /tmp/old/' _", "find ~ -print0 | xargs -0 -I{} mv {} /tmp/old/",
    "find ~ | xargs -I{} sh -c 'mv {} /tmp/old/'", "ls -A | xargs mv -t /tmp/old", "echo ~ | xargs -I{} mv {} /tmp/old/",
])
def test_an_xargs_fed_mv_judges_the_feed(command):
    assert held_in_three_modes(command), (command, held(command).rule)


def test_an_xargs_fed_mv_of_a_narrowed_feed_stays_allowed():
    assert allowed_in("find build -name '*.o' -print0 | xargs -0 -I{} mv {} dist/", SRC_X)
    assert held("find build -name '*.o' -print0 | xargs -0 mv -t dist").allow


def test_a_feed_positional_is_a_name_not_an_empty_string():
    assert held("find build -name '*.d' -print0 | xargs -0 -n1 sh -c 'rm -rf \"$0\"/*'").allow     # not `rm -rf /*`
    assert is_held("find ~ -print0 | xargs -0 -n1 sh -c 'rm -rf \"$0\"/*'")


# ---------------------------------------------------------------- adversary round 8 (PR 939) LOW-1 & LOW-2

@pytest.mark.parametrize("command", [
    "find ~ -mindepth 1 -maxdepth 1 -exec rimraf {} +",
    "find ~ -mindepth 1 -maxdepth 1 -exec rip {} +",
    "find ~ -mindepth 1 -maxdepth 1 -exec del-cli {} +",
    "find ~ -mindepth 1 -maxdepth 1 -exec trash {} +",
    "find ~ -mindepth 1 -maxdepth 1 -exec trash-put {} +",
    'find "$OUT"/ -mindepth 1 -maxdepth 1 -exec rimraf {} +',
    'find "$OUT"/ -mindepth 1 -maxdepth 1 -exec trash {} +',
])
def test_find_exec_with_non_core_remover_names_is_held(command):
    """PR 939 r8 LOW-1: REMOVER_NAMES outside REMOVERS must not slip past find -exec."""
    assert held_in_three_modes(command), (command, held(command).rule)


def test_find_exec_with_non_core_remover_on_safe_target_stays_allowed():
    assert held("find build -name '*.o' -exec trash {} +").allow
    assert allowed_in("find build -name '*.o' -exec rimraf {} +", SRC_X)


@pytest.mark.parametrize("command", [
    "find ~ -mindepth 1 -maxdepth 1 -exec mv {} /tmp/old/ \\;",
    'find "$OUT"/ -mindepth 1 -maxdepth 1 -exec mv {} /tmp/old/ \\;',
    "find ~ -mindepth 1 -maxdepth 1 -exec gmv {} /tmp/old/ \\;",
    "find ~ -mindepth 1 -maxdepth 1 -exec chmod -R 777 {} \\;",
    "find ~ -mindepth 1 -maxdepth 1 -exec chown -R nobody {} \\;",
    "find ~ -mindepth 1 -maxdepth 1 -exec git -C {} clean -fdx \\;",
    "find ~ -mindepth 1 -maxdepth 1 -exec rsync -a --delete e/ {} \\;",
    "find ~ -maxdepth 1 | parallel mv {} /tmp/old/",
    "find ~ -maxdepth 1 | parallel -j4 gmv {} /tmp/old/",
    "find ~ -maxdepth 1 | parallel chmod -R 777 {}",
    "find ~ -maxdepth 1 | parallel -j 4 chown --recursive nobody {}",
    "find ~ -maxdepth 1 | parallel git -C {} clean -fdx",
    "find ~ -maxdepth 1 | parallel rsync -a --delete e/ {}",
    "find ~ -maxdepth 1 | parallel 'mv {} /tmp/old/'",
    "find ~ -maxdepth 1 | parallel 'chmod -R 777 {}'",
    "find ~ -maxdepth 1 | parallel 'git -C {} clean -fdx'",
    "find ~ -maxdepth 1 | xargs chmod -R 777",
    "find ~ -maxdepth 1 | xargs -n1 rsync -a --delete e/",
    "find ~ -maxdepth 1 | xargs -I{} git -C {} clean -fdx",
    "xargs -I{} chmod -R 777 {}",
    "xargs -I{} rsync -a --delete e/ {}",
    "xargs -I{} git -C {} clean -fdx",
])
def test_fed_mv_recursive_changer_git_clean_and_rsync_delete_are_held(command):
    """PR 939 r8 LOW-2: fed mv, chmod -R, git clean and rsync --delete are held in all three modes."""
    assert held_in_three_modes(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "find build -name '*.o' -exec mv {} dist/ \\;",
    "find build -name '*.sh' -exec chmod +x {} \\;",
    "find build -name '*.d' -exec chmod -R 755 {} \\;",
    "find build -name '*.d' -exec git -C {} status \\;",
    "find build -name '*.d' -exec git -C {} clean -nd \\;",
    "find build -name '*.d' -exec rsync -a --delete e/ {} \\;",
    "find build -name '*.sh' | xargs chmod +x",
    "find build -name '*.d' | xargs chmod -R 755",
    "find build -name '*.d' | xargs -n1 rsync -a --delete e/",
    "find ~ -maxdepth 1 | xargs -n1 rsync -a e/",
    "find ~ -maxdepth 1 | xargs -I{} git -C {} status",
    "find ~ -maxdepth 1 | xargs -I{} git -C {} clean -nd",
    "find build | parallel echo {}",
    "find build | parallel chmod +x {}",
    "find build | parallel git -C {} status",
    "find build | parallel git -C {} clean -nd",
    "find build | parallel rsync -a e/ {}",
    "parallel echo {} ::: mv",
])
def test_safe_non_destructive_find_xargs_and_parallel_shapes_stay_allowed(command):
    assert allowed_in(command, SRC_X), (command, held(command).rule)


# ---------------------------------------------------------------- adversary PR 953 round 1 (MED-1, LOW-1..3)

@pytest.mark.parametrize("command", [
    "find build -name '*.d' -exec rsync -a --delete e/ ~ \\;",
    "find build -name '*.d' -exec rsync -a --delete {} / \\;",
    "find build -name '*.d' -exec rsync -a --delete {} ~ \\;",
    "find build -name '*.d' -exec rsync -a --delete e/ \"$D\"/ \\;",
    "find build -name '*.d' -exec rsync -a --delete \\;",
])
def test_find_exec_rsync_delete_judges_destination_operand(command):
    """PR 953 MED-1: exempting --delete inside find -exec rsync must still judge non-{} destinations (and empty operands)."""
    assert held_in_three_modes(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "find ~ -maxdepth 1 | parallel echo hi \\; mv {} /tmp/old/",
    "find ~ -maxdepth 1 | parallel true \\&\\& mv {} /tmp/old/",
    "find ~ -maxdepth 1 | parallel : \\; chmod -R 777 {}",
    "find ~ -maxdepth 1 | parallel : \\; git -C {} clean -fdx",
    "parallel sh -c {} ::: 'mv ~ /tmp/old/'",
    "parallel {} ::: 'mv ~ /tmp/old/'",
    "parallel : \\; sh -c {} ::: 'chmod -R 777 ~'",
])
def test_parallel_escaped_separators_and_tail_payloads_are_held(command):
    """PR 953 LOW-1: parallel checks every separated sub-command and inspects ::: payloads when cmd runs them."""
    assert held_in_three_modes(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "find ~ -mindepth 1 -maxdepth 1 -exec env -S 'mv {} /tmp/old/' \\;",
    "find ~ -mindepth 1 -maxdepth 1 -exec env -S 'chmod -R 777 {}' \\;",
    "find ~ -mindepth 1 -maxdepth 1 -exec env -S 'git -C {} clean -fdx' \\;",
])
def test_find_exec_env_split_string_is_held(command):
    """PR 953 LOW-2: find -exec does not discard env -S split-string from _chain."""
    assert held_in_three_modes(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "find ~ -mindepth 1 -maxdepth 1 -exec git -c clean.requireForce=off clean -d {} \\;",
    "find ~ -mindepth 1 -maxdepth 1 -exec git -c clean.requireForce= clean -d {} \\;",
    "find ~ -mindepth 1 -maxdepth 1 -exec git -cclean.requireForce=false clean -d {} \\;",
    "find ~ -mindepth 1 -maxdepth 1 -exec git -cclean.requireForce=off clean -d {} \\;",
])
def test_find_exec_git_clean_requireforce_off_and_attached_c_are_held(command):
    """PR 953 LOW-3: _is_git_clean recognizes =off, =, and attached -c... forms."""
    assert held_in_three_modes(command), (command, held(command).rule)


@pytest.mark.parametrize("command", [
    "git -c clean.requireForce=off clean -d",
    "git -c clean.requireForce= clean -d",
    "git -cclean.requireForce=false clean -d",
    "git -cclean.requireForce=off clean -d",
])
def test_git_clean_requireforce_off_and_attached_c_are_held_at_home(command):
    """PR 953 LOW-3: top-level git() recognizes =off, =, and attached -c... forms."""
    assert not allowed_in(command, HOME), (command, held(command).rule)
    assert allowed_in(command, SRC_X), (command, held(command).rule)
